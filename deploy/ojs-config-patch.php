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

// Base URL — OJS is served under /app via nginx
$c = preg_replace('#^base_url = .*#m', 'base_url = "https://genrxiv.org/app"', $c);

// Journal-specific base URL
if (!preg_match('/^base_url\[genrxiv\]/m', $c)) {
    $c = preg_replace('/^(base_url = .*$)/m', "$1\nbase_url[genrxiv] = https://genrxiv.org/app/genrxiv", $c);
} else {
    $c = preg_replace('/^base_url\[genrxiv\] = .*$/m', 'base_url[genrxiv] = https://genrxiv.org/app/genrxiv', $c);
}

// Trust X-Forwarded-For from nginx
$c = preg_replace('/^trust_x_forwarded_for = .*/m', 'trust_x_forwarded_for = On', $c);

// App key — generate if empty
if (preg_match('/^app_key =\s*$/m', $c)) {
    $key = 'base64:' . base64_encode(random_bytes(32));
    $c = preg_replace('/^app_key =\s*$/m', "app_key = $key", $c);
}

// SMTP email settings from env (Resend or any SMTP relay)
$smtpHost = getenv('SMTP_HOST');
$smtpPort = getenv('SMTP_PORT');
$smtpUser = getenv('SMTP_USERNAME');
$smtpPass = getenv('SMTP_PASSWORD');
$smtpAuth = getenv('SMTP_AUTH');

if ($smtpHost) {
    // Switch from sendmail to smtp
    $c = preg_replace('/^default = sendmail/m', 'default = smtp', $c);

    // Enable SMTP
    if (preg_match('/^;\s*smtp = On/m', $c)) {
        $c = preg_replace('/^;\s*smtp = On/m', 'smtp = On', $c);
    } elseif (!preg_match('/^smtp = On/m', $c)) {
        $c = preg_replace('/^(default = smtp)/m', "$1\nsmtp = On", $c);
    }

    // SMTP server
    $c = preg_replace('/^;\s*smtp_server = .*/m', "smtp_server = $smtpHost", $c);
    if (!preg_match('/^smtp_server = /m', $c)) {
        $c = preg_replace('/^(smtp = On)/m', "$1\nsmtp_server = $smtpHost", $c);
    }

    // SMTP port
    $c = preg_replace('/^;\s*smtp_port = .*/m', "smtp_port = $smtpPort", $c);
    if (!preg_match('/^smtp_port = /m', $c)) {
        $c = preg_replace('/^(smtp_server = .*)/m', "$1\nsmtp_port = $smtpPort", $c);
    }

    // SMTP auth
    if ($smtpAuth) {
        $c = preg_replace('/^;\s*smtp_auth = .*/m', "smtp_auth = $smtpAuth", $c);
        if (!preg_match('/^smtp_auth = /m', $c)) {
            $c = preg_replace('/^(smtp_port = .*)/m', "$1\nsmtp_auth = $smtpAuth", $c);
        }
    }

    // SMTP username
    if ($smtpUser) {
        $c = preg_replace('/^;\s*smtp_username = .*/m', "smtp_username = $smtpUser", $c);
        if (!preg_match('/^smtp_username = /m', $c)) {
            $c = preg_replace('/^(smtp_auth = .*)/m', "$1\nsmtp_username = $smtpUser", $c);
        }
    }

    // SMTP password
    if ($smtpPass) {
        $c = preg_replace('/^;\s*smtp_password = .*/m', "smtp_password = $smtpPass", $c);
        if (!preg_match('/^smtp_password = /m', $c)) {
            $c = preg_replace('/^(smtp_username = .*)/m', "$1\nsmtp_password = $smtpPass", $c);
        }
    }

    // Envelope sender — use a no-reply at genrxiv.org
    $c = preg_replace('/^;\s*allow_envelope_sender = Off/m', 'allow_envelope_sender = On', $c);
    $c = preg_replace('/^;\s*default_envelope_sender = .*/m', 'default_envelope_sender = no-reply@genrxiv.org', $c);
    $c = preg_replace('/^;\s*force_default_envelope_sender = Off/m', 'force_default_envelope_sender = On', $c);
    $c = preg_replace('/^;\s*force_dmarc_compliant_from = Off/m', 'force_dmarc_compliant_from = On', $c);

    echo "[OJS Config Patch] Configured SMTP: $smtpHost:$smtpPort\n";
}

file_put_contents($conf, $c);
echo "[OJS Config Patch] Applied database and host settings to $conf\n";
