<?php
/**
 * @file plugins/themes/genrxiv/GenrxivPlugin.php
 *
 * GenRxiv custom theme — child of the default OJS theme.
 * Applies the GenRxiv brand: paper background, ink text, cobalt accent,
 * Fraunces serif headings, IBM Plex Sans body.
 */

namespace APP\plugins\themes\genrxiv;

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

        // Remove the default theme's color option — we use our own palette
        $this->removeStyleOption('baseColour');
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
}
