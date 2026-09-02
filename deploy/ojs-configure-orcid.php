<?php
// Enable and configure ORCID in OJS
// The client ID and secret can be set via env vars or filled in later
define('INDEX_FILE_LOCATION', '/var/www/html/index.php');
require '/var/www/html/lib/pkp/includes/bootstrap.php';

use APP\core\Application;
use APP\journal\JournalDAO;

$journalDao = DAORegistry::getDAO('JournalDAO');
$journal = $journalDao->getByPath('genrxiv');

if (!$journal) {
    echo "[ORCID Config] Journal not found, skipping\n";
    exit;
}

// Enable ORCID at the site level
$siteDao = DAORegistry::getDAO('SiteDAO');
$site = $siteDao->getSite();

// Set ORCID settings from env vars if available
$clientId = getenv('ORCID_CLIENT_ID') ?: '';
$clientSecret = getenv('ORCID_CLIENT_SECRET') ?: '';

// Enable ORCID globally
$site->setData('orcidEnabled', true);
// Set API type to public production (not sandbox)
$site->setData('orcidApiType', 'publicProduction');
$siteDao->updateObject($site);
echo "[ORCID Config] Enabled ORCID at site level (production API)\n";

// Set client credentials at site level (globally configured)
if ($clientId) {
    $site->setData('orcidClientId', $clientId);
    echo "[ORCID Config] Set ORCID client ID\n";
}
if ($clientSecret) {
    $site->setData('orcidClientSecret', $clientSecret);
    echo "[ORCID Config] Set ORCID client secret\n";
}
$siteDao->updateObject($site);

$journalDao->updateObject($journal);

if (!$clientId || !$clientSecret) {
    echo "[ORCID Config] WARNING: ORCID client ID/secret not set.\n";
    echo "[ORCID Config] Register at https://orcid.org/developer-tools\n";
    echo "[ORCID Config] Set redirect URI to: https://genrxiv.org/app/genrxiv/orcidVerify\n";
    echo "[ORCID Config] Then set ORCID_CLIENT_ID and ORCID_CLIENT_SECRET in .env\n";
}
