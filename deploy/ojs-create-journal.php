<?php
// Create the GenRxiv journal context in OJS
define('INDEX_FILE_LOCATION', '/var/www/html/index.php');
require '/var/www/html/lib/pkp/includes/bootstrap.php';

use APP\core\Application;
use APP\journal\Journal;
use APP\journal\JournalDAO;

$journalDao = DAORegistry::getDAO('JournalDAO');

// Check if journal already exists
$existing = $journalDao->getByPath('genrxiv');
if ($existing) {
    echo "[Create Journal] Journal already exists with ID: " . $existing->getId() . "\n";
    exit;
}

$journal = $journalDao->newDataObject();
$journal->setPath('genrxiv');
$journal->setPrimaryLocale('en');
$journal->setEnabled(true);
$journal->setName('GenRxiv', 'en');
$journal->setDescription('An open archive for AI-generated research', 'en');

$journalId = $journalDao->insertObject($journal);
echo "[Create Journal] Created journal with ID: " . $journalId . "\n";
