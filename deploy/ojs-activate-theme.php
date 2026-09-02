<?php
// Activate the GenRxiv theme in the database
// Run after OJS install to ensure the theme is registered and active

$host = getenv('PKP_DB_HOST') ?: 'db';
$name = getenv('PKP_DB_NAME') ?: 'ojs';
$user = getenv('PKP_DB_USER') ?: 'ojs';
$pass = getenv('PKP_DB_PASSWORD') ?: '';

if (empty($pass)) {
    echo "[Theme Activate] No DB password, skipping\n";
    exit;
}

$dsn = "pgsql:host=$host;dbname=$name";
try {
    $pdo = new PDO($dsn, $user, $pass);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

    // Check if genrxiv theme is already in versions table
    $stmt = $pdo->prepare("SELECT count(*) FROM versions WHERE product_type = 'plugins.themes' AND product = 'genrxiv'");
    $stmt->execute();
    $exists = $stmt->fetchColumn();

    if (!$exists) {
        $pdo->exec("INSERT INTO versions (major, minor, revision, build, date_installed, current, product_type, product, product_class_name, lazy_load, sitewide) VALUES (1, 0, 0, 0, NOW(), 1, 'plugins.themes', 'genrxiv', 'GenrxivPlugin', 1, 0)");
        echo "[Theme Activate] Registered genrxiv theme in versions table\n";
    }

    // Enable the plugin at site level
    $stmt = $pdo->prepare("SELECT count(*) FROM plugin_settings WHERE plugin_name = 'genrxivplugin' AND setting_name = 'enabled' AND context_id IS NULL");
    $stmt->execute();
    $enabled = $stmt->fetchColumn();

    if (!$enabled) {
        $pdo->exec("INSERT INTO plugin_settings (plugin_name, context_id, setting_name, setting_value, setting_type) VALUES ('genrxivplugin', NULL, 'enabled', '1', 'bool')");
        echo "[Theme Activate] Enabled genrxiv plugin (site)\n";
    }

    // Enable the plugin at journal level (context_id = 1)
    $stmt = $pdo->prepare("SELECT count(*) FROM plugin_settings WHERE plugin_name = 'genrxivplugin' AND setting_name = 'enabled' AND context_id = 1");
    $stmt->execute();
    $journalEnabled = $stmt->fetchColumn();

    if (!$journalEnabled) {
        $pdo->exec("INSERT INTO plugin_settings (plugin_name, context_id, setting_name, setting_value, setting_type) VALUES ('genrxivplugin', 1, 'enabled', '1', 'bool')");
        echo "[Theme Activate] Enabled genrxiv plugin (journal)\n";
    }

    // Set as active theme at site level
    $pdo->exec("UPDATE site_settings SET setting_value = 'genrxiv' WHERE setting_name = 'themePluginPath'");
    echo "[Theme Activate] Set genrxiv as active theme (site)\n";

    // Also set at journal level (context_id = 1)
    $stmt = $pdo->prepare("SELECT count(*) FROM journal_settings WHERE setting_name = 'themePluginPath' AND journal_id = 1");
    $stmt->execute();
    $journalTheme = $stmt->fetchColumn();

    if (!$journalTheme) {
        $pdo->exec("INSERT INTO journal_settings (journal_id, setting_name, setting_value, locale) VALUES (1, 'themePluginPath', 'genrxiv', '')");
        echo "[Theme Activate] Set genrxiv as active theme (journal)\n";
    } else {
        $pdo->exec("UPDATE journal_settings SET setting_value = 'genrxiv' WHERE setting_name = 'themePluginPath' AND journal_id = 1");
        echo "[Theme Activate] Updated genrxiv theme (journal)\n";
    }

} catch (Exception $e) {
    echo "[Theme Activate] Error: " . $e->getMessage() . "\n";
}
