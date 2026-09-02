<?php
// Register and enable the AI Disclosure plugin
define('INDEX_FILE_LOCATION', '/var/www/html/index.php');
require '/var/www/html/lib/pkp/includes/bootstrap.php';

use APP\core\Application;

$host = getenv('PKP_DB_HOST') ?: 'db';
$name = getenv('PKP_DB_NAME') ?: 'ojs';
$user = getenv('PKP_DB_USER') ?: 'ojs';
$pass = getenv('PKP_DB_PASSWORD') ?: '';

$dsn = "pgsql:host=$host;dbname=$name";
try {
    $pdo = new PDO($dsn, $user, $pass);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

    // Register AI Disclosure plugin in versions table
    $stmt = $pdo->prepare("SELECT count(*) FROM versions WHERE product_type = 'plugins.generic' AND product = 'aiDisclosure'");
    $stmt->execute();
    $exists = $stmt->fetchColumn();

    if (!$exists) {
        $pdo->exec("INSERT INTO versions (major, minor, revision, build, date_installed, current, product_type, product, product_class_name, lazy_load, sitewide) VALUES (1, 0, 0, 0, NOW(), 1, 'plugins.generic', 'aiDisclosure', 'AiDisclosurePlugin', 1, 0)");
        echo "[Plugins] Registered aiDisclosure plugin in versions table\n";
    }

    // Enable the plugin (plugin_name must be LOWER(product_class_name) = aidisclosureplugin)
    $stmt = $pdo->prepare("SELECT count(*) FROM plugin_settings WHERE plugin_name = 'aidisclosureplugin' AND setting_name = 'enabled'");
    $stmt->execute();
    $enabled = $stmt->fetchColumn();

    if (!$enabled) {
        $pdo->exec("INSERT INTO plugin_settings (plugin_name, context_id, setting_name, setting_value, setting_type) VALUES ('aidisclosureplugin', NULL, 'enabled', '1', 'bool')");
        echo "[Plugins] Enabled aiDisclosure plugin\n";
    }

    // Also enable at journal level (context_id = 1)
    $stmt = $pdo->prepare("SELECT count(*) FROM plugin_settings WHERE plugin_name = 'aidisclosureplugin' AND setting_name = 'enabled' AND context_id = 1");
    $stmt->execute();
    $journalEnabled = $stmt->fetchColumn();

    if (!$journalEnabled) {
        $pdo->exec("INSERT INTO plugin_settings (plugin_name, context_id, setting_name, setting_value, setting_type) VALUES ('aidisclosureplugin', 1, 'enabled', '1', 'bool')");
        echo "[Plugins] Enabled aiDisclosure plugin for journal\n";
    }

    // --- LaTeX Compiler plugin ---
    $stmt = $pdo->prepare("SELECT count(*) FROM versions WHERE product_type = 'plugins.generic' AND product = 'latexCompiler'");
    $stmt->execute();
    $exists = $stmt->fetchColumn();

    if (!$exists) {
        $pdo->exec("INSERT INTO versions (major, minor, revision, build, date_installed, current, product_type, product, product_class_name, lazy_load, sitewide) VALUES (1, 0, 0, 0, NOW(), 1, 'plugins.generic', 'latexCompiler', 'LatexCompilerPlugin', 1, 0)");
        echo "[Plugins] Registered latexCompiler plugin in versions table\n";
    }

    $stmt = $pdo->prepare("SELECT count(*) FROM plugin_settings WHERE plugin_name = 'latexcompilerplugin' AND setting_name = 'enabled'");
    $stmt->execute();
    $enabled = $stmt->fetchColumn();

    if (!$enabled) {
        $pdo->exec("INSERT INTO plugin_settings (plugin_name, context_id, setting_name, setting_value, setting_type) VALUES ('latexcompilerplugin', NULL, 'enabled', '1', 'bool')");
        echo "[Plugins] Enabled latexCompiler plugin\n";
    }

    $stmt = $pdo->prepare("SELECT count(*) FROM plugin_settings WHERE plugin_name = 'latexcompilerplugin' AND setting_name = 'enabled' AND context_id = 1");
    $stmt->execute();
    $journalEnabled = $stmt->fetchColumn();

    if (!$journalEnabled) {
        $pdo->exec("INSERT INTO plugin_settings (plugin_name, context_id, setting_name, setting_value, setting_type) VALUES ('latexcompilerplugin', 1, 'enabled', '1', 'bool')");
        echo "[Plugins] Enabled latexCompiler plugin for journal\n";
    }

    // --- Submission Policy plugin ---
    $stmt = $pdo->prepare("SELECT count(*) FROM versions WHERE product_type = 'plugins.generic' AND product = 'submissionPolicy'");
    $stmt->execute();
    $exists = $stmt->fetchColumn();

    if (!$exists) {
        $pdo->exec("INSERT INTO versions (major, minor, revision, build, date_installed, current, product_type, product, product_class_name, lazy_load, sitewide) VALUES (1, 0, 0, 0, NOW(), 1, 'plugins.generic', 'submissionPolicy', 'SubmissionPolicyPlugin', 1, 0)");
        echo "[Plugins] Registered submissionPolicy plugin in versions table\n";
    }

    $stmt = $pdo->prepare("SELECT count(*) FROM plugin_settings WHERE plugin_name = 'submissionpolicyplugin' AND setting_name = 'enabled' AND context_id IS NULL");
    $stmt->execute();
    $enabled = $stmt->fetchColumn();

    if (!$enabled) {
        $pdo->exec("INSERT INTO plugin_settings (plugin_name, context_id, setting_name, setting_value, setting_type) VALUES ('submissionpolicyplugin', NULL, 'enabled', '1', 'bool')");
        echo "[Plugins] Enabled submissionPolicy plugin (site)\n";
    }

    $stmt = $pdo->prepare("SELECT count(*) FROM plugin_settings WHERE plugin_name = 'submissionpolicyplugin' AND setting_name = 'enabled' AND context_id = 1");
    $stmt->execute();
    $journalEnabled = $stmt->fetchColumn();

    if (!$journalEnabled) {
        $pdo->exec("INSERT INTO plugin_settings (plugin_name, context_id, setting_name, setting_value, setting_type) VALUES ('submissionpolicyplugin', 1, 'enabled', '1', 'bool')");
        echo "[Plugins] Enabled submissionPolicy plugin (journal)\n";
    }

} catch (Exception $e) {
    echo "[Plugins] Error: " . $e->getMessage() . "\n";
}
