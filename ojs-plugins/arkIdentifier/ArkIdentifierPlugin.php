<?php
/**
 * @file plugins/generic/arkIdentifier/ArkIdentifierPlugin.php
 *
 * ARK (Archival Resource Key) persistent identifier plugin for GenRxiv.
 *
 * Generates an ARK for each preprint when it is published. The ARK is:
 *   https://n2t.net/ark:/<NAAN>/genrxiv-<base32-id>
 *
 * Where:
 *   - NAAN is the Name Assigning Authority Number (from CDL/n2t.net)
 *   - The suffix is "genrxiv-" followed by a short base32-encoded random ID
 *
 * ARKs are stored as submission metadata and displayed on the article page.
 * They are included in OAI-PMH Dublin Core output as dc:identifier.
 *
 * Until a real NAAN is assigned by CDL, the placeholder "99999" (test NAAN)
 * is used. Swap ARK_NAAN below or set the ARK_NAAN env var to change it.
 */

namespace APP\plugins\generic\arkIdentifier;

use APP\core\Application;
use APP\facades\Repo;
use APP\plugins\generic\arkIdentifier\ArkIdentifierPlugin;
use PKP\plugins\GenericPlugin;
use PKP\plugins\Hook;

class ArkIdentifierPlugin extends GenericPlugin
{
    // Test NAAN — replace with the real NAAN assigned by CDL
    public const DEFAULT_NAAN = '99999';
    public const ARK_PREFIX = 'genrxiv';
    public const RESOLVER_URL = 'https://n2t.net/ark:/';
    public const SETTING_NAME = 'arkIdentifier';

    public function register($category, $path, $mainContextId = null)
    {
        if (!parent::register($category, $path, $mainContextId)) {
            return false;
        }

        if ($this->getEnabled($mainContextId)) {
            // Assign ARK when a publication is published
            Hook::add('Publication::publish', $this->assignArk(...));
            // Display ARK on the article page
            Hook::add('TemplateManager::display', $this->handleTemplateDisplay(...));
            // Include ARK in OAI-PMH Dublin Core metadata
            Hook::add('OAIMetadataFormat::findJournalEntry', $this->addToOai(...));
            Hook::add('OAIMetadataFormat::findRecordEntry', $this->addToOai(...));
        }

        return true;
    }

    public function getDisplayName()
    {
        return __('plugins.generic.arkIdentifier.name');
    }

    public function getDescription()
    {
        return __('plugins.generic.arkIdentifier.description');
    }

    public function getCanEnable()
    {
        return true;
    }

    /**
     * Get the configured NAAN (Name Assigning Authority Number).
     */
    protected function getNaan(): string
    {
        $envNaan = getenv('ARK_NAAN');
        return $envNaan ?: self::DEFAULT_NAAN;
    }

    /**
     * Generate a short, unique ARK suffix.
     * Uses base32 (Crockford encoding, lowercase) for readability.
     */
    protected function generateSuffix(): string
    {
        // 8 random bytes = 13 base32 chars, plenty of uniqueness
        $bytes = random_bytes(8);
        $hex = bin2hex($bytes);
        $num = gmp_init($hex, 16);
        $base32 = gmp_strval($num, 32);
        // Crockford base32 uses 0-9 and a-v (excluding i, l, o, u)
        $base32 = strtr($base32, 'iou', 'jkw');
        return self::ARK_PREFIX . '-' . $base32;
    }

    /**
     * Construct the full ARK URL.
     */
    public function constructArkUrl(string $suffix): string
    {
        return self::RESOLVER_URL . $this->getNaan() . '/' . $suffix;
    }

    /**
     * Assign an ARK to a submission when its publication is published.
     */
    public function assignArk($hookName, $args)
    {
        $newPublication = $args[0];
        $submission = Repo::submission()->get($newPublication->getData('submissionId'));

        if (!$submission) {
            return;
        }

        // Check if ARK already exists
        $existingArk = $submission->getData(self::SETTING_NAME);
        if ($existingArk) {
            return;
        }

        // Generate a unique ARK
        $suffix = $this->generateSuffix();
        $arkUrl = $this->constructArkUrl($suffix);

        // Store the ARK on the submission
        $submission->setData(self::SETTING_NAME, $arkUrl);
        Repo::submission()->dao->update($submission);

        error_log("[ARK] Assigned $arkUrl to submission " . $submission->getId());
    }

    /**
     * Inject ARK into the article page template.
     */
    public function handleTemplateDisplay($hookName, $args)
    {
        $templateMgr = $args[0];
        $template = $args[1];

        // Only modify article detail pages
        if (strpos($template, 'frontend/pages/article.tpl') === false &&
            strpos($template, 'frontend/objects/article_details.tpl') === false) {
            return;
        }

        $submission = $templateMgr->getTemplateVars('submission');
        if (!$submission) {
            return;
        }

        $ark = $submission->getData(self::SETTING_NAME);
        if ($ark) {
            $templateMgr->assign('arkIdentifier', $ark);
        }
    }

    /**
     * Add ARK to OAI-PMH metadata output.
     */
    public function addToOai($hookName, $args)
    {
        $record = $args[0];
        $submission = $args[1] ?? null;

        if (!$submission) {
            return;
        }

        $ark = $submission->getData(self::SETTING_NAME);
        if ($ark) {
            // Add as dc:identifier in Dublin Core
            if (isset($record['identifier']) && is_array($record['identifier'])) {
                $record['identifier'][] = $ark;
            } elseif (isset($record['identifier'])) {
                $record['identifier'] = [$record['identifier'], $ark];
            } else {
                $record['identifier'] = [$ark];
            }
        }
    }
}
