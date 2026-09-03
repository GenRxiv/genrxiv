<?php
/**
 * @file plugins/generic/markdownRenderer/MarkdownRendererPlugin.php
 *
 * GenRxiv Markdown Renderer plugin.
 *
 * When a .md file is uploaded as a submission file, this plugin calls
 * the convert-service to render it:
 *
 * 1. HTML galley (primary) — via /render/html, with KaTeX math,
 *    and print-friendly CSS. This is the version of record displayed
 *    on the article page.
 *
 * 2. PDF galley (secondary) — via /convert/markdown. Provided for
 *    readers who want a downloadable PDF, but the HTML is the
 *    canonical view.
 *
 * GenRxiv accepts Markdown submissions only — no LaTeX, no PDF uploads.
 * The Markdown source is the version of record.
 */

namespace APP\plugins\generic\markdownRenderer;

use APP\core\Application;
use APP\facades\Repo;
use PKP\config\Config;
use PKP\file\TemporaryFileManager;
use PKP\plugins\GenericPlugin;
use PKP\plugins\Hook;

class MarkdownRendererPlugin extends GenericPlugin
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
        return __('plugins.generic.markdownRenderer.name');
    }

    public function getDescription()
    {
        return __('plugins.generic.markdownRenderer.description');
    }

    public function getCanEnable()
    {
        return true;
    }

    /**
     * Called when a submission file is added.
     * If it's a .md file, render it to HTML and PDF galleys.
     */
    public function onFileAdded($hookName, $args)
    {
        $submissionFile = $args[0];
        $fileExtension = strtolower(pathinfo($submissionFile->getOriginalFileName(), PATHINFO_EXTENSION));

        if (!in_array($fileExtension, ['md', 'markdown'])) {
            return;
        }

        $this->renderFile($submissionFile);
    }

    /**
     * Render a Markdown submission file using the convert-service.
     * Produces an HTML galley (primary) and a PDF galley (secondary).
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

        $convertUrl = getenv('CONVERT_SERVICE_URL') ?: 'http://convert:8000';

        // --- 1. Render HTML galley (primary) ---
        $htmlResult = $this->callConvertService(
            $convertUrl . '/render/html',
            $filePath,
            $originalFileName
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
            error_log("[MarkdownRenderer] Rendered $originalFileName to HTML for submission $submissionId");
        } else {
            error_log("[MarkdownRenderer] Failed to render HTML for $originalFileName");
        }

        // --- 2. Compile PDF galley (secondary, for download) ---
        $pdfResult = $this->callConvertService(
            $convertUrl . '/convert/markdown',
            $filePath,
            $originalFileName
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
            error_log("[MarkdownRenderer] Compiled $originalFileName to PDF for submission $submissionId");
        } else {
            error_log("[MarkdownRenderer] Failed to compile PDF for $originalFileName (HTML may still be available)");
        }
    }

    /**
     * Call the convert-service with a file upload.
     * Returns the response body on success, null on failure.
     */
    private function callConvertService($url, $filePath, $originalFileName)
    {
        $tmpFile = tempnam(sys_get_temp_dir(), 'genrxiv_upload_');
        copy($filePath, $tmpFile);

        $ch = curl_init();
        curl_setopt($ch, CURLOPT_URL, $url);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, 120);
        curl_setopt($ch, CURLOPT_POSTFIELDS, [
            'file' => new \CURLFile($tmpFile, 'text/markdown', $originalFileName),
        ]);

        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $error = curl_error($ch);
        curl_close($ch);

        unlink($tmpFile);

        if ($httpCode !== 200 || $error) {
            error_log("[MarkdownRenderer] Convert-service call to $url failed: HTTP $httpCode, error: $error");
            return null;
        }

        return $response;
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
