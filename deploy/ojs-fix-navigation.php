<?php
/**
 * Fix navigation menus for the GenRxiv journal context.
 *
 * OJS's CLI install creates navigation menu items at the site level
 * (context_id = NULL), but the menu DAO queries with
 * COALESCE(context_id, 0) = <journal_context_id>, so site-level items
 * are never found for a journal context. This script moves the user
 * navigation menu and its items to context_id = 1, and creates a
 * primary navigation menu with About and Submissions items.
 */

define('INDEX_FILE_LOCATION', '/var/www/html/index.php');
require '/var/www/html/lib/pkp/includes/bootstrap.php';

use PKP\core\Core;
use PKP\db\DAORegistry;

$journalDao = DAORegistry::getDAO('JournalDAO');
$journal = $journalDao->getByPath('genrxiv');
if (!$journal) {
    echo "[Nav Fix] Journal 'genrxiv' not found, skipping\n";
    exit;
}
$contextId = $journal->getId();
echo "[Nav Fix] Fixing navigation for context $contextId\n";

$db = Core::getDB();

// Move the user navigation menu to the journal context
$db->execute(
    "UPDATE navigation_menus SET context_id = ? WHERE area_name = 'user' AND context_id IS NULL",
    [(int)$contextId]
);

// Move user navigation menu items to the journal context
$db->execute(
    "UPDATE navigation_menu_items SET context_id = ? WHERE context_id IS NULL AND type LIKE 'NMI_TYPE_USER%'",
    [(int)$contextId]
);

// Create a primary navigation menu for the journal if it doesn't exist
$result = $db->retrieve(
    "SELECT navigation_menu_id FROM navigation_menus WHERE area_name = 'primary' AND COALESCE(context_id, 0) = ?",
    [(int)$contextId]
);
$row = (array)$result->current();
$primaryMenuId = $row['navigation_menu_id'] ?? null;

if (!$primaryMenuId) {
    $db->execute(
        "INSERT INTO navigation_menus (context_id, area_name, title) VALUES (?, 'primary', 'Primary Navigation Menu')",
        [(int)$contextId]
    );
    $result = $db->retrieve(
        "SELECT navigation_menu_id FROM navigation_menus WHERE area_name = 'primary' AND COALESCE(context_id, 0) = ?",
        [(int)$contextId]
    );
    $row = (array)$result->current();
    $primaryMenuId = $row['navigation_menu_id'];
    echo "[Nav Fix] Created primary navigation menu (id=$primaryMenuId)\n";
} else {
    echo "[Nav Fix] Primary navigation menu already exists (id=$primaryMenuId)\n";
}

// Add About and Submissions items if they don't exist
foreach ([
    ['NMI_TYPE_ABOUT', 'navigation.about'],
    ['NMI_TYPE_SUBMISSIONS', 'navigation.submissions'],
] as [$type, $titleKey]) {
    $result = $db->retrieve(
        "SELECT navigation_menu_item_id FROM navigation_menu_items WHERE type = ? AND COALESCE(context_id, 0) = ?",
        [$type, (int)$contextId]
    );
    $row = (array)$result->current();
    $itemId = $row['navigation_menu_item_id'] ?? null;

    if (!$itemId) {
        $db->execute(
            "INSERT INTO navigation_menu_items (context_id, type) VALUES (?, ?)",
            [(int)$contextId, $type]
        );
        $result = $db->retrieve(
            "SELECT navigation_menu_item_id FROM navigation_menu_items WHERE type = ? AND COALESCE(context_id, 0) = ?",
            [$type, (int)$contextId]
        );
        $row = (array)$result->current();
        $itemId = $row['navigation_menu_item_id'];

        $db->execute(
            "INSERT INTO navigation_menu_item_settings (navigation_menu_item_id, locale, setting_name, setting_value, setting_type) VALUES (?, '', 'titleLocaleKey', ?, 'string')",
            [(int)$itemId, $titleKey]
        );
        echo "[Nav Fix] Created nav item: $type (id=$itemId)\n";
    }

    // Assign to primary menu if not already assigned
    $result = $db->retrieve(
        "SELECT navigation_menu_item_assignment_id FROM navigation_menu_item_assignments WHERE navigation_menu_id = ? AND navigation_menu_item_id = ?",
        [(int)$primaryMenuId, (int)$itemId]
    );
    $row = (array)$result->current();
    if (!$row) {
        $seq = ($type === 'NMI_TYPE_ABOUT') ? 0 : 1;
        $db->execute(
            "INSERT INTO navigation_menu_item_assignments (navigation_menu_id, navigation_menu_item_id, seq) VALUES (?, ?, ?)",
            [(int)$primaryMenuId, (int)$itemId, $seq]
        );
        echo "[Nav Fix] Assigned $type to primary menu (seq=$seq)\n";
    }
}

// Clear the navigation menu cache
$db->execute("DELETE FROM caches WHERE cache_name LIKE 'navigationMenu%'");
echo "[Nav Fix] Done\n";
