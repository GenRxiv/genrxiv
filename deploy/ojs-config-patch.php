<?php
// Patch OJS config.inc.php with correct settings
$conf = '/var/www/html/config.inc.php';
$c = file_get_contents($conf);

// Database driver
$c = preg_replace('/^driver = .*/m', 'driver = postgres9', $c);

// Database host
$c = preg_replace('/^host = .*/m', 'host = db', $c);

// Database credentials from env
if (getenv('PKP_DB_PASSWORD')) {
    $c = preg_replace('/^password = .*/m', 'password = ' . getenv('PKP_DB_PASSWORD'), $c);
}
if (getenv('PKP_DB_NAME')) {
    $c = preg_replace('/^name = .*/m', 'name = ' . getenv('PKP_DB_NAME'), $c);
}
if (getenv('PKP_DB_USER')) {
    $c = preg_replace('/^username = .*/m', 'username = ' . getenv('PKP_DB_USER'), $c);
}

// Allowed hosts
$c = preg_replace('/^allowed_hosts = .*/m', "allowed_hosts = '[\"genrxiv.org\", \"localhost\"]'", $c);

file_put_contents($conf, $c);
echo "[OJS Config Patch] Applied database and host settings to $conf\n";
