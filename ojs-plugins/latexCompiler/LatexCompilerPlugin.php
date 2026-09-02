<?php
/**
 * @file plugins/generic/latexCompiler/LatexCompilerPlugin.php
 *
 * GenRxiv LaTeX/Markdown Compiler plugin.
 *
 * When a .tex, .md, or .zip file is uploaded as a submission file,
 * this plugin calls the convert-service to compile it to PDF and
 * attaches the resulting PDF as a galley file.
 */

namespace APP\plugins\generic\latexCompiler;

use APP\core\Application;
use APP\facades\Repo;
use PKP\config\Config;
use PKP\file\TemporaryFileManager;
use PKP\plugins\GenericPlugin;
use PKP\plugins\Hook;

class LatexCompilerPlugin extends GenericPlugin
{
    public function register($category, $path, $mainContextId = null)
    {
        if (!parent::register($category, $path, $mainContextId)) {
            return false;
        }

        if ($this->getEnabled($mainContextId)) {
            Hook::add('SubmissionFile::add', $this->onFileAdded(...));
        }

        return true;
    }

    public function getDisplayName()
    {
        return __('plugins.generic.latexCompiler.name');
    }

    public function getDescription()
    {
        return __('plugins.generic.latexCompiler.description');
    }

    public function getCanEnable()
    {
        return true;
    }

    /**
     * Called when a submission file is added.
     * If it's a .tex, .md, or .zip file, compile it to PDF.
     */
    public function onFileAdded($hookName, $args)
    {
        $submissionFile = $args[0];
        $fileExtension = pathinfo($submissionFile->getOriginalFileName(), PATHINFO_EXTENSION);

        $compilableExtensions = ['tex', 'md', 'zip'];
        if (!in_array(strtolower($fileExtension), $compilableExtensions)) {
            return;
        }

        $this->compileFile($submissionFile);
    }

    /**
     * Compile a submission file using the convert-service.
     */
    private function compileFile($submissionFile)
    {
        $request = Application::get()->getRequest();
        $context = $request->getContext();
        if (!$context) {
            return;
        }

        // Get the file path on disk
        $submissionId = $submissionFile->getData('submissionId');
        $fileId = $submissionFile->getData('fileId');
        $genreId = $submissionFile->getData('genreId');

        // Get the actual file
        $file = Repo::file()->get($fileId);
        if (!$file) {
            return;
        }

        $filePath = $file->path;
        if (!file_exists($filePath)) {
            return;
        }

        $originalFileName = $submissionFile->getOriginalFileName();
        $fileExtension = strtolower(pathinfo($originalFileName, PATHINFO_EXTENSION));

        // Determine the convert endpoint
        $endpoint = $fileExtension === 'md' ? 'convert/markdown' : 'convert/latex';

        // Get convert-service URL from config or default
        $convertUrl = getenv('CONVERT_SERVICE_URL') ?: 'http://convert:8000';

        // Prepare the file for upload
        $tmpFile = tempnam(sys_get_temp_dir(), 'genrxiv_compile_');
        copy($filePath, $tmpFile);

        // Send to convert-service
        $ch = curl_init();
        curl_setopt($ch, CURLOPT_URL, $convertUrl . '/' . $endpoint);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, 120);
        curl_setopt($ch, CURLOPT_POSTFIELDS, [
            'file' => new \CURLFile($tmpFile, mime_content_type($filePath), $originalFileName),
        ]);

        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $error = curl_error($ch);
        curl_close($ch);

        unlink($tmpFile);

        if ($httpCode !== 200 || $error) {
            error_log("[LatexCompiler] Failed to compile $originalFileName: HTTP $httpCode, error: $error");
            return;
        }

        // The response is a PDF file
        $pdfTmpFile = tempnam(sys_get_temp_dir(), 'genrxiv_pdf_') . '.pdf';
        file_put_contents($pdfTmpFile, $response);

        // Attach the PDF as a submission file (galley)
        $this->attachPdfToSubmission($submissionId, $pdfTmpFile, $genreId, $context->getId());

        @unlink($pdfTmpFile);

        error_log("[LatexCompiler] Successfully compiled $originalFileName to PDF for submission $submissionId");
    }

    /**
     * Attach a compiled PDF to the submission as a galley file.
     */
    private function attachPdfToSubmission($submissionId, $pdfPath, $genreId, $contextId)
    {
        $submission = Repo::submission()->get($submissionId);
        if (!$submission) {
            return;
        }

        // Get the first publication
        $publications = $submission->getData('publications');
        if (empty($publications)) {
            return;
        }
        $publication = $publications[0];

        // Create a new file
        $fileManager = new TemporaryFileManager();
        $fileName = 'compiled.pdf';

        // Read the PDF
        $fileContent = file_get_contents($pdfPath);
        $fileSize = strlen($fileContent);

        // Use the submission file repository to add the file
        $submissionDir = Repo::submissionFile()->getSubmissionDir($contextId, $submissionId);
        $fileStage = SUBMISSION_FILE_PROOF; // Proof file stage (galley)

        // Get the genre for the PDF (try to find a "PDF" genre or use the same genre)
        $genreDao = DAORegistry::getDAO('GenreDAO');
        $genres = $genreDao->getByContextId($contextId);
        $pdfGenreId = $genreId;
        while ($genre = $genres->next()) {
            if (strpos(strtolower($genre->getLocalizedName()), 'pdf') !== false) {
                $pdfGenreId = $genre->getId();
                break;
            }
        }

        // Write the file to the submission directory
        $fileId = Repo::file()->add(
            $fileContent,
            $fileName,
            $contextId,
            $submissionDir
        );

        // Create the submission file record
        $submissionFile = Repo::submissionFile()->newDataObject();
        $submissionFile->setData('submissionId', $submissionId);
        $submissionFile->setData('fileId', $fileId);
        $submissionFile->setData('genreId', $pdfGenreId);
        $submissionFile->setData('fileStage', $fileStage);
        $submissionFile->setData('originalFileName', $fileName);
        $submissionFile->setData('name', 'Compiled PDF', 'en');
        $submissionFile->setData('viewable', true);
        $submissionFile->setData('assocType', ASSOC_TYPE_SUBMISSION);
        $submissionFile->setData('assocId', $submissionId);

        Repo::submissionFile()->add($submissionFile);
    }
}
