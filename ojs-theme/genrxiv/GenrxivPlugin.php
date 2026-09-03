<?php
/**
 * @file plugins/themes/genrxiv/GenrxivPlugin.php
 *
 * GenRxiv custom theme — child of the default OJS theme.
 * Applies the GenRxiv brand: paper background, ink text, cobalt accent,
 * Fraunces serif headings, IBM Plex Sans body.
 *
 * Also injects Schema.org ScholarlyArticle JSON-LD into article pages
 * for machine-readable metadata (search engines, AI crawlers, citation
 * managers).
 */

namespace APP\plugins\themes\genrxiv;

use APP\core\Application;
use APP\facades\Repo;
use PKP\plugins\Hook;

class GenrxivPlugin extends \APP\plugins\themes\default\DefaultThemePlugin
{
    /**
     * Initialize the theme — add our custom styles on top of the parent.
     */
    public function init()
    {
        // Let the parent theme initialize first
        parent::init();

        // Add our custom override stylesheet (loaded after parent styles)
        $this->addStyle(
            'genrxiv-custom',
            'styles/genrxiv.less',
            ['context' => 'frontend']
        );
    }

    /**
     * Register the theme and hooks.
     */
    public function register($category, $path, $mainContextId = null)
    {
        if (!parent::register($category, $path, $mainContextId)) {
            return false;
        }

        // Inject Schema.org JSON-LD into article pages
        Hook::add('TemplateManager::display', $this->injectJsonLd(...));

        return true;
    }

    /**
     * Get the display name.
     */
    public function getDisplayName()
    {
        return __('plugins.themes.genrxiv.name');
    }

    /**
     * Get the description.
     */
    public function getDescription()
    {
        return __('plugins.themes.genrxiv.description');
    }

    /**
     * Inject Schema.org ScholarlyArticle JSON-LD into article pages.
     */
    public function injectJsonLd($hookName, $args)
    {
        $templateMgr = $args[0];
        $template = $args[1];

        // Only inject on article pages
        if ($template !== 'frontend/pages/article.tpl') {
            return;
        }

        $article = $templateMgr->getTemplateVars('article');
        $publication = $templateMgr->getTemplateVars('publication');
        $context = $templateMgr->getTemplateVars('currentContext');

        if (!$article || !$publication) {
            return;
        }

        $jsonLd = $this->buildJsonLd($article, $publication, $context);
        if ($jsonLd) {
            $templateMgr->addHeader(
                'genrxiv-jsonld',
                '<script type="application/ld+json">' . json_encode($jsonLd, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . '</script>'
            );
        }
    }

    /**
     * Build the Schema.org ScholarlyArticle JSON-LD object.
     */
    protected function buildJsonLd($article, $publication, $context): array
    {
        $request = Application::get()->getRequest();
        $articleUrl = $request->getDispatcher()->url(
            $request,
            Application::ROUTE_PAGE,
            $context->getPath(),
            'article',
            'view',
            [$article->getId()],
            urlLocaleForPage: '',
        );

        // Title
        $title = $publication->getLocalizedTitle(null, 'text');
        $title = strip_tags($title);

        // Abstract
        $abstract = $publication->getLocalizedAbstract();
        if ($abstract) {
            $abstract = strip_tags($abstract);
        }

        // Authors
        $authors = [];
        foreach ($publication->getData('authors') as $author) {
            $authorData = [
                '@type' => 'Person',
                'name' => $author->getFullName(),
            ];
            $givenName = $author->getLocalizedGivenName();
            $familyName = $author->getLocalizedFamilyName();
            if ($givenName) {
                $authorData['givenName'] = $givenName;
            }
            if ($familyName) {
                $authorData['familyName'] = $familyName;
            }
            $orcid = $author->getOrcid();
            if ($orcid) {
                $authorData['@id'] = $orcid;
                $authorData['identifier'] = $orcid;
            }
            $affiliation = $author->getLocalizedAffiliation();
            if ($affiliation) {
                $authorData['affiliation'] = [
                    '@type' => 'Organization',
                    'name' => strip_tags($affiliation),
                ];
            }
            $authors[] = $authorData;
        }

        // Date published
        $datePublished = $publication->getData('datePublished');

        // License
        $licenseUrl = $publication->getData('licenseUrl');

        // Build the JSON-LD object
        $jsonLd = [
            '@context' => 'https://schema.org',
            '@type' => 'ScholarlyArticle',
            'url' => $articleUrl,
        ];

        if ($title) {
            $jsonLd['headline'] = $title;
        }
        if ($abstract) {
            $jsonLd['abstract'] = $abstract;
        }
        if (count($authors) > 0) {
            $jsonLd['author'] = $authors;
        }
        if ($datePublished) {
            $jsonLd['datePublished'] = $datePublished;
            $jsonLd['dateModified'] = $datePublished;
        }
        if ($licenseUrl) {
            $jsonLd['license'] = $licenseUrl;
        }

        // Journal/publisher info
        $jsonLd['isPartOf'] = [
            '@type' => 'PublicationVolume',
            'name' => $context->getLocalizedData('name'),
            'publisher' => [
                '@type' => 'Organization',
                'name' => $context->getLocalizedData('publisherInstitution') ?: $context->getLocalizedData('name'),
            ],
        ];

        // Language
        $locale = $publication->getData('locale');
        if ($locale) {
            $jsonLd['inLanguage'] = substr($locale, 0, 2);
        }

        // ARK identifier if present
        $ark = $article->getData('arkIdentifier');
        if ($ark) {
            $jsonLd['identifier'] = $ark;
        }

        // Keywords
        $keywords = $publication->getLocalizedData('keywords');
        if ($keywords && is_array($keywords)) {
            $jsonLd['keywords'] = implode(', ', $keywords);
        } elseif ($keywords && is_string($keywords)) {
            $jsonLd['keywords'] = $keywords;
        }

        return $jsonLd;
    }
}
