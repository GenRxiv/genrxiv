<?php
/**
 * Fix journal settings that the CLI install didn't set properly.
 *
 * The CLI install creates the journal but doesn't set locale settings
 * or journal-level user groups. This script ensures:
 * - Locale settings (primaryLocale, supportedLocales, etc.)
 * - Journal-level user groups (manager, author, reviewer, etc.)
 * - Admin user assigned to manager and author roles
 */

define('INDEX_FILE_LOCATION', '/var/www/html/index.php');
require '/var/www/html/lib/pkp/includes/bootstrap.php';

use PKP\core\Core;
use PKP\db\DAORegistry;

$journalDao = DAORegistry::getDAO('JournalDAO');
$journal = $journalDao->getByPath('genrxiv');
if (!$journal) {
    echo "[Journal Fix] Journal 'genrxiv' not found, skipping\n";
    exit;
}
$contextId = $journal->getId();
echo "[Journal Fix] Fixing settings for context $contextId\n";

$db = Core::getDB();

// ─── Locale settings ──────────────────────────────────────────────
// OJS 3.5 uses 'en' not 'en_US'
$localeSettings = [
    'primaryLocale' => 'en',
    'supportedLocales' => '["en"]',
    'supportedFormLocales' => '["en"]',
    'supportedSubmissionLocales' => '["en"]',
    'supportedSubmissionMetadataLocales' => '["en"]',
    'supportedAddedSubmissionLocales' => '["en"]',
    'defaultSubmissionLocale' => 'en',
];

foreach ($localeSettings as $name => $value) {
    $result = $db->retrieve(
        "SELECT setting_value FROM journal_settings WHERE journal_id = ? AND setting_name = ? AND locale = ''",
        [(int)$contextId, $name]
    );
    $row = (array)$result->current();
    if (!isset($row['setting_value'])) {
        $db->execute(
            "INSERT INTO journal_settings (journal_id, locale, setting_name, setting_value) VALUES (?, '', ?, ?)",
            [(int)$contextId, $name, $value]
        );
        echo "[Journal Fix] Set $name = $value\n";
    }
}

// ─── Journal-level user groups ────────────────────────────────────
// The CLI install only creates a site-level admin group (context_id=NULL).
// The journal needs its own user groups for roles to work.
$roleGroups = [
    1 => [0, 0, 1, 1, 1],        // ROLE_ID_SITE_ADMIN
    16 => [0, 0, 1, 1, 1],       // ROLE_ID_MANAGER
    17 => [0, 0, 1, 0, 1],       // ROLE_ID_SUB_EDITOR
    65536 => [1, 1, 1, 0, 0],    // ROLE_ID_AUTHOR
    4096 => [1, 1, 0, 0, 1],     // ROLE_ID_REVIEWER
    4097 => [0, 0, 1, 0, 0],     // ROLE_ID_ASSISTANT
    1048576 => [0, 1, 0, 0, 0],  // ROLE_ID_READER
];

foreach ($roleGroups as $roleId => $flags) {
    [$isDefault, $showTitle, $permitMetadata, $permitSettings, $masthead] = $flags;
    $result = $db->retrieve(
        "SELECT user_group_id FROM user_groups WHERE context_id = ? AND role_id = ?",
        [(int)$contextId, $roleId]
    );
    $row = (array)$result->current();
    if (!isset($row['user_group_id'])) {
        $db->execute(
            "INSERT INTO user_groups (context_id, role_id, is_default, show_title, permit_self_registration, permit_metadata_edit, permit_settings, masthead) VALUES (?, ?, 1, ?, 0, ?, ?, ?)",
            [(int)$contextId, $roleId, $showTitle, $permitMetadata, $permitSettings, $masthead]
        );
        echo "[Journal Fix] Created user group for role $roleId\n";
    }
}

// ─── Assign admin to manager and author groups ────────────────────
$adminUserId = 1;

// Find the manager group
$result = $db->retrieve(
    "SELECT user_group_id FROM user_groups WHERE context_id = ? AND role_id = 16",
    [(int)$contextId]
);
$row = (array)$result->current();
$managerGroupId = $row['user_group_id'] ?? null;

// Find the author group
$result = $db->retrieve(
    "SELECT user_group_id FROM user_groups WHERE context_id = ? AND role_id = 65536",
    [(int)$contextId]
);
$row = (array)$result->current();
$authorGroupId = $row['user_group_id'] ?? null;

foreach ([$managerGroupId, $authorGroupId] as $groupId) {
    if ($groupId) {
        $result = $db->retrieve(
            "SELECT user_id FROM user_user_groups WHERE user_id = ? AND user_group_id = ?",
            [$adminUserId, (int)$groupId]
        );
        $row = (array)$result->current();
        if (!isset($row['user_id'])) {
            $db->execute(
                "INSERT INTO user_user_groups (user_id, user_group_id) VALUES (?, ?)",
                [$adminUserId, (int)$groupId]
            );
            echo "[Journal Fix] Assigned admin to user group $groupId\n";
        }
    }
}

// ─── Fix admin email ──────────────────────────────────────────────
$db->execute(
    "UPDATE users SET email = 'admin@genrxiv.org' WHERE username = 'admin' AND email != 'admin@genrxiv.org'"
);

// ─── Set journal contact emails ───────────────────────────────────
foreach (['contactEmail', 'supportEmail'] as $emailSetting) {
    $result = $db->retrieve(
        "SELECT setting_value FROM journal_settings WHERE journal_id = ? AND setting_name = ? AND locale = ''",
        [(int)$contextId, $emailSetting]
    );
    $row = (array)$result->current();
    if (!isset($row['setting_value'])) {
        $db->execute(
            "INSERT INTO journal_settings (journal_id, locale, setting_name, setting_value) VALUES (?, '', ?, 'admin@genrxiv.org')",
            [(int)$contextId, $emailSetting]
        );
        echo "[Journal Fix] Set $emailSetting = admin@genrxiv.org\n";
    }
}

// Clear cache
$db->execute("DELETE FROM caches WHERE cache_name LIKE 'navigationMenu%'");
echo "[Journal Fix] Done\n";
