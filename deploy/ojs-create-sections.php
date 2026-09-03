<?php
// Create journal sections for GenRxiv
define('INDEX_FILE_LOCATION', '/var/www/html/index.php');
require '/var/www/html/lib/pkp/includes/bootstrap.php';

use APP\facades\Repo;
use APP\journal\JournalDAO;

$journalDao = DAORegistry::getDAO('JournalDAO');
$journal = $journalDao->getByPath('genrxiv');

if (!$journal) {
    echo "[Sections] Journal not found, skipping\n";
    exit;
}

$journalId = $journal->getId();

// Check if sections already exist
$existing = Repo::section()->getCollector()
    ->filterByContextIds([$journalId])
    ->getMany();

if ($existing->count() > 0) {
    $titles = [];
    foreach ($existing as $s) {
        $titles[] = $s->getLocalizedTitle('en');
    }
    echo "[Sections] Already exist: " . implode(', ', $titles) . "\n";
    exit;
}

// Create "Preprints" section
$section = Repo::section()->newDataObject();
$section->setContextId($journalId);
$section->setReviewFormId(null);
$section->setSequence(1);
$section->setEditorRestricted(false);
$section->setMetaIndexed(true);
$section->setMetaReviewed(false);
$section->setAbstractsNotRequired(false);
$section->setHideTitle(false);
$section->setHideAuthor(false);
$section->setIsInactive(false);
$section->setTitle('Preprints', 'en');
$section->setAbbrev('PRE', 'en');
$section->setPolicy('All AI-generated or AI-co-generated research submissions. Each preprint must include a disclosure of AI involvement.', 'en');

$sectionId = Repo::section()->add($section);
echo "[Sections] Created 'Preprints' section with ID: $sectionId\n";
