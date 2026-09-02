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

    // Enable the plugin
    $stmt = $pdo->prepare("SELECT count(*) FROM plugin_settings WHERE plugin_name = 'genrxivplugin' AND setting_name = 'enabled'");
    $stmt->execute();
    $enabled = $stmt->fetchColumn();

    if (!$enabled) {
        $pdo->exec("INSERT INTO plugin_settings (plugin_name, context_id, setting_name, setting_value, setting_type) VALUES ('genrxivplugin', NULL, 'enabled', '1', 'bool')");
        echo "[Theme Activate] Enabled genrxiv plugin\n";
    }

    // Set as active theme
    $pdo->exec("UPDATE site_settings SET setting_value = 'genrxiv' WHERE setting_name = 'themePluginPath'");
    echo "[Theme Activate] Set genrxiv as active theme\n";

} catch (Exception $e) {
    echo "[Theme Activate] Error: " . $e->getMessage() . "\n";
}
