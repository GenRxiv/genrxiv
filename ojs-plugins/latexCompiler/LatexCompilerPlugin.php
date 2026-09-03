<?php
/**
 * @file plugins/generic/latexCompiler/LatexCompilerPlugin.php
 *
 * GenRxiv LaTeX/Markdown Compiler plugin.
 *
 * When a .tex, .md, or .zip file is uploaded as a submission file,
 * this plugin calls the convert-service to render it:
 *
 * 1. HTML galley (primary) — via /render/html, with KaTeX math,
 *    SVG figures, and print-friendly CSS. This is the version of
 *    record displayed on the article page.
 *
 * 2. PDF galley (on-demand) — via /convert/latex or /convert/markdown.
 *    Provided for readers who want a downloadable PDF, but the HTML
 *    is the canonical view.
 *
 * This keeps storage small: source + HTML is ~50-200 KB per paper
 * vs 2-10 MB for a PDF with embedded fonts and images.
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
     * If it's a .tex, .md, or .zip file, render it to HTML and PDF.
     */
    public function onFileAdded($hookName, $args)
    {
        $submissionFile = $args[0];
        $fileExtension = pathinfo($submissionFile->getOriginalFileName(), PATHINFO_EXTENSION);

        $compilableExtensions = ['tex', 'md', 'markdown', 'zip'];
        if (!in_array(strtolower($fileExtension), $compilableExtensions)) {
            return;
        }

        $this->renderFile($submissionFile);
    }

    /**
     * Render a submission file using the convert-service.
     * Produces an HTML galley (primary) and optionally a PDF galley.
     */
    private function renderFile($submissionFile)
    {
        $request = Application::get()->getRequest();
        $context = $request->getContext();
        if (!$context) {
            return;
        }

        $submissionId = $submissionFile->getData('submissionId');
        $fileId = $submissionFile->getData('fileId');
        $genreId = $submissionFile->getData('genreId');

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

        $convertUrl = getenv('CONVERT_SERVICE_URL') ?: 'http://convert:8000';

        // --- 1. Render HTML galley (primary) ---
        $htmlResult = $this->callConvertService(
            $convertUrl . '/render/html',
            $filePath,
            $originalFileName,
            $fileExtension
        );

        if ($htmlResult) {
            $htmlTmpFile = tempnam(sys_get_temp_dir(), 'genrxiv_html_') . '.html';
            file_put_contents($htmlTmpFile, $htmlResult);
            $this->attachGalleyToSubmission(
                $submissionId,
                $htmlTmpFile,
                'article.html',
                'text/html',
                'HTML (primary)',
                $genreId,
                $context->getId()
            );
            @unlink($htmlTmpFile);
            error_log("[LatexCompiler] Rendered $originalFileName to HTML for submission $submissionId");
        } else {
            error_log("[LatexCompiler] Failed to render HTML for $originalFileName");
        }

        // --- 2. Compile PDF galley (secondary, for download) ---
        $endpoint = in_array($fileExtension, ['md', 'markdown']) ? 'convert/markdown' : 'convert/latex';
        $pdfResult = $this->callConvertService(
            $convertUrl . '/' . $endpoint,
            $filePath,
            $originalFileName,
            $fileExtension
        );

        if ($pdfResult) {
            $pdfTmpFile = tempnam(sys_get_temp_dir(), 'genrxiv_pdf_') . '.pdf';
            file_put_contents($pdfTmpFile, $pdfResult);
            $this->attachGalleyToSubmission(
                $submissionId,
                $pdfTmpFile,
                'compiled.pdf',
                'application/pdf',
                'PDF (download)',
                $genreId,
                $context->getId()
            );
            @unlink($pdfTmpFile);
            error_log("[LatexCompiler] Compiled $originalFileName to PDF for submission $submissionId");
        } else {
            error_log("[LatexCompiler] Failed to compile PDF for $originalFileName (HTML may still be available)");
        }
    }

    /**
     * Call the convert-service with a file upload.
     * Returns the response body on success, null on failure.
     */
    private function callConvertService($url, $filePath, $originalFileName, $fileExtension)
    {
        $tmpFile = tempnam(sys_get_temp_dir(), 'genrxiv_upload_');
        copy($filePath, $tmpFile);

        $postFields = [];
        if ($fileExtension === 'zip') {
            // For zips, we need to specify the main file
            // Try common entry points
            $mainFile = $this->findMainFileInZip($tmpFile);
            if ($mainFile) {
                $postFields['main_file'] = $mainFile;
            }
        }
        $postFields['file'] = new \CURLFile($tmpFile, mime_content_type($filePath), $originalFileName);

        $ch = curl_init();
        curl_setopt($ch, CURLOPT_URL, $url);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, 120);
        curl_setopt($ch, CURLOPT_POSTFIELDS, $postFields);

        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $error = curl_error($ch);
        curl_close($ch);

        unlink($tmpFile);

        if ($httpCode !== 200 || $error) {
            error_log("[LatexCompiler] Convert-service call to $url failed: HTTP $httpCode, error: $error");
            return null;
        }

        return $response;
    }

    /**
     * Find the likely main .tex or .md file in a zip.
     */
    private function findMainFileInZip($zipPath)
    {
        $zip = new \ZipArchive();
        if ($zip->open($zipPath) !== true) {
            return null;
        }

        $candidates = ['paper.tex', 'main.tex', 'article.tex', 'manuscript.tex',
                       'paper.md', 'main.md', 'article.md', 'manuscript.md'];
        $allFiles = [];

        for ($i = 0; $i < $zip->numFiles; $i++) {
            $name = $zip->getNameIndex($i);
            $allFiles[] = $name;
        }

        // First, look for exact matches to common names
        foreach ($candidates as $candidate) {
            if (in_array($candidate, $allFiles)) {
                $zip->close();
                return $candidate;
            }
        }

        // Then, look for any .tex or .md file
        foreach ($allFiles as $name) {
            $ext = strtolower(pathinfo($name, PATHINFO_EXTENSION));
            if (in_array($ext, ['tex', 'md', 'markdown'])) {
                $zip->close();
                return $name;
            }
        }

        $zip->close();
        return null;
    }

    /**
     * Attach a rendered file to the submission as a galley.
     */
    private function attachGalleyToSubmission($submissionId, $filePath, $fileName, $mimeType, $name, $genreId, $contextId)
    {
        $submission = Repo::submission()->get($submissionId);
        if (!$submission) {
            return;
        }

        $publications = $submission->getData('publications');
        if (empty($publications)) {
            return;
        }
        $publication = $publications[0];

        $fileContent = file_get_contents($filePath);

        $submissionDir = Repo::submissionFile()->getSubmissionDir($contextId, $submissionId);
        $fileStage = SUBMISSION_FILE_PROOF;

        // Find an appropriate genre for the file type
        $genreDao = DAORegistry::getDAO('GenreDAO');
        $genres = $genreDao->getByContextId($contextId);
        $targetGenreId = $genreId;

        $searchTerm = strpos($mimeType, 'html') !== false ? 'html' : 'pdf';
        while ($genre = $genres->next()) {
            if (strpos(strtolower($genre->getLocalizedName()), $searchTerm) !== false) {
                $targetGenreId = $genre->getId();
                break;
            }
        }

        $fileId = Repo::file()->add(
            $fileContent,
            $fileName,
            $contextId,
            $submissionDir
        );

        $submissionFile = Repo::submissionFile()->newDataObject();
        $submissionFile->setData('submissionId', $submissionId);
        $submissionFile->setData('fileId', $fileId);
        $submissionFile->setData('genreId', $targetGenreId);
        $submissionFile->setData('fileStage', $fileStage);
        $submissionFile->setData('originalFileName', $fileName);
        $submissionFile->setData('name', $name, 'en');
        $submissionFile->setData('viewable', true);
        $submissionFile->setData('assocType', ASSOC_TYPE_SUBMISSION);
        $submissionFile->setData('assocId', $submissionId);

        Repo::submissionFile()->add($submissionFile);
    }
}
