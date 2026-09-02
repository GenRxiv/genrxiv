<?php
/**
 * @file plugins/generic/aiDisclosure/AiDisclosurePlugin.php
 *
 * GenRxiv AI Disclosure plugin.
 *
 * Adds AI involvement disclosure fields to OJS publications:
 * - aiInvolvementLevel: assisted, coGenerated, or fullyGenerated
 * - aiModelsUsed: free text describing models and their roles
 * - aiDisclosureStatement: plain-language disclosure statement
 * - citationsVerified: boolean confirming human verification of citations
 *
 * These fields are:
 * 1. Added to the publication schema via Schema::get::publication hook
 * 2. Displayed on the article view page via Templates::Article::Main hook
 * 3. Validated on publication via Publication::validate hook
 */

namespace APP\plugins\generic\aiDisclosure;

use APP\core\Application;
use APP\template\TemplateManager;
use PKP\plugins\GenericPlugin;
use PKP\plugins\Hook;

class AiDisclosurePlugin extends GenericPlugin
{
    public function register($category, $path, $mainContextId = null)
    {
        if (!parent::register($category, $path, $mainContextId)) {
            return false;
        }

        if ($this->getEnabled($mainContextId)) {
            // Extend the publication schema with AI disclosure fields
            Hook::add('Schema::get::publication', $this->extendSchema(...));
            // Display AI disclosure on the article page
            Hook::add('Templates::Article::Main', $this->displayDisclosure(...));
            // Validate AI disclosure fields on publication
            Hook::add('Publication::validate', $this->validateDisclosure(...));
        }

        return true;
    }

    public function getDisplayName()
    {
        return __('plugins.generic.aiDisclosure.name');
    }

    public function getDescription()
    {
        return __('plugins.generic.aiDisclosure.description');
    }

    public function getCanEnable()
    {
        return true;
    }

    /**
     * Extend the publication schema with AI disclosure fields.
     */
    public function extendSchema($hookName, $args)
    {
        $schema = &$args[0];
        if (!isset($schema->properties)) {
            return;
        }

        $schema->properties->aiInvolvementLevel = (object) [
            'type' => 'string',
            'description' => 'Level of AI involvement: assisted, coGenerated, or fullyGenerated',
            'validation' => ['nullable', 'in:assisted,coGenerated,fullyGenerated'],
            'apiSummary' => true,
        ];

        $schema->properties->aiModelsUsed = (object) [
            'type' => 'string',
            'multilingual' => false,
            'description' => 'AI models used and their roles',
            'validation' => ['nullable'],
        ];

        $schema->properties->aiDisclosureStatement = (object) [
            'type' => 'string',
            'multilingual' => true,
            'description' => 'Plain-language AI disclosure statement',
            'validation' => ['nullable'],
        ];

        $schema->properties->citationsVerified = (object) [
            'type' => 'boolean',
            'description' => 'Whether citations and numerical claims have been verified by human authors',
            'validation' => ['nullable'],
            'apiSummary' => true,
        ];
    }

    /**
     * Display AI disclosure information on the article view page.
     */
    public function displayDisclosure($hookName, $args)
    {
        $templateMgr = $args[0] ?? TemplateManager::getManager(Application::get()->getRequest());
        $publication = $templateMgr->getTemplateVars('publication');

        if (!$publication) {
            return;
        }

        $aiInvolvementLevel = $publication->getData('aiInvolvementLevel');
        $aiModelsUsed = $publication->getData('aiModelsUsed');
        $aiDisclosureStatement = $publication->getLocalizedData('aiDisclosureStatement');
        $citationsVerified = $publication->getData('citationsVerified');

        // Only display if any field is set
        if (!$aiInvolvementLevel && !$aiModelsUsed && !$aiDisclosureStatement && $citationsVerified === null) {
            return;
        }

        $levelLabels = [
            'assisted' => __('plugins.generic.aiDisclosure.field.aiInvolvementLevel.assisted'),
            'coGenerated' => __('plugins.generic.aiDisclosure.field.aiInvolvementLevel.coGenerated'),
            'fullyGenerated' => __('plugins.generic.aiDisclosure.field.aiInvolvementLevel.fullyGenerated'),
        ];

        $levelLabel = $levelLabels[$aiInvolvementLevel] ?? $aiInvolvementLevel;

        $html = '<div class="item ai_disclosure">';
        $html .= '<div class="label">' . __('plugins.generic.aiDisclosure.display.title') . '</div>';
        $html .= '<div class="value">';

        if ($aiInvolvementLevel) {
            $html .= '<div class="sub_item">';
            $html .= '<div class="label">' . __('plugins.generic.aiDisclosure.display.aiInvolvementLevel') . '</div>';
            $html .= '<div class="value">' . htmlspecialchars($levelLabel) . '</div>';
            $html .= '</div>';
        }

        if ($aiModelsUsed) {
            $html .= '<div class="sub_item">';
            $html .= '<div class="label">' . __('plugins.generic.aiDisclosure.display.aiModelsUsed') . '</div>';
            $html .= '<div class="value">' . nl2br(htmlspecialchars($aiModelsUsed)) . '</div>';
            $html .= '</div>';
        }

        if ($aiDisclosureStatement) {
            $html .= '<div class="sub_item">';
            $html .= '<div class="label">' . __('plugins.generic.aiDisclosure.display.aiDisclosureStatement') . '</div>';
            $html .= '<div class="value">' . nl2br(htmlspecialchars($aiDisclosureStatement)) . '</div>';
            $html .= '</div>';
        }

        if ($citationsVerified !== null) {
            $html .= '<div class="sub_item">';
            $html .= '<div class="label">' . __('plugins.generic.aiDisclosure.display.citationsVerified') . '</div>';
            $html .= '<div class="value">' . ($citationsVerified ? __('plugins.generic.aiDisclosure.display.citationsVerified.yes') : __('plugins.generic.aiDisclosure.display.citationsVerified.no')) . '</div>';
            $html .= '</div>';
        }

        $html .= '</div></div>';

        echo $html;
    }

    /**
     * Validate AI disclosure fields — require them for published submissions.
     */
    public function validateDisclosure($hookName, $args)
    {
        $errors = &$args[0];
        $publication = $args[1];
        $props = $args[2];

        // Only validate on publish, not on draft edits
        if (isset($props['status']) && $props['status'] === \PKP\submission\PKPSubmission::STATUS_PUBLISHED) {
            if (empty($props['aiInvolvementLevel']) && empty($publication->getData('aiInvolvementLevel'))) {
                $errors['aiInvolvementLevel'] = [__('plugins.generic.aiDisclosure.field.aiInvolvementLevel') . ' is required'];
            }
            if (empty($props['aiModelsUsed']) && empty($publication->getData('aiModelsUsed'))) {
                $errors['aiModelsUsed'] = [__('plugins.generic.aiDisclosure.field.aiModelsUsed') . ' is required'];
            }
        }
    }
}
