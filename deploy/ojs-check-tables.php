<?php
// Check if OJS tables exist in the database
// Uses env vars directly instead of parsing config.inc.php
$host = getenv('PKP_DB_HOST') ?: 'db';
$name = getenv('PKP_DB_NAME') ?: 'ojs';
$user = getenv('PKP_DB_USER') ?: 'ojs';
$pass = getenv('PKP_DB_PASSWORD') ?: '';

if (empty($pass)) {
    echo "0";
    exit;
}

$dsn = "pgsql:host=$host;dbname=$name";
try {
    $pdo = new PDO($dsn, $user, $pass);
    $count = $pdo->query("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")->fetchColumn();
    echo $count;
} catch (Exception $e) {
    echo "0";
}
