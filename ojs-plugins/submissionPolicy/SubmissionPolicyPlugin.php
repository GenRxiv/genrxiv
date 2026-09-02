<?php
/**
 * @file plugins/generic/submissionPolicy/SubmissionPolicyPlugin.php
 *
 * GenRxiv Submission Policy plugin.
 *
 * Enforces submission policies:
 * 1. ORCID required — only users with a verified ORCID iD can submit
 * 2. Rate limit — max 2 submissions per 7-day rolling window per user
 *
 * Both policies are enforced via the Submission::validateSubmit hook,
 * which fires before a submission is created.
 */

namespace APP\plugins\generic\submissionPolicy;

use APP\core\Application;
use APP\facades\Repo;
use PKP\db\DB;
use PKP\plugins\GenericPlugin;
use PKP\plugins\Hook;

class SubmissionPolicyPlugin extends GenericPlugin
{
    public const MAX_SUBMISSIONS_PER_WEEK = 2;
    public const RATE_LIMIT_DAYS = 7;

    public function register($category, $path, $mainContextId = null)
    {
        if (!parent::register($category, $path, $mainContextId)) {
            return false;
        }

        if ($this->getEnabled($mainContextId)) {
            Hook::add('Submission::validateSubmit', $this->validateSubmit(...));
        }

        return true;
    }

    public function getDisplayName()
    {
        return __('plugins.generic.submissionPolicy.name');
    }

    public function getDescription()
    {
        return __('plugins.generic.submissionPolicy.description');
    }

    public function getCanEnable()
    {
        return true;
    }

    /**
     * Enforce submission policies before a submission is created.
     */
    public function validateSubmit($hookName, $args)
    {
        $errors = &$args[0];
        $submission = $args[1];
        $context = $args[2];

        $request = Application::get()->getRequest();
        $user = $request->getUser();

        if (!$user) {
            return;
        }

        // Policy 1: Require a verified ORCID iD
        if (!$user->hasVerifiedOrcid()) {
            $errors['orcidRequired'] = [__('plugins.generic.submissionPolicy.orcidRequired')];
        }

        // Policy 2: Rate limit — max 2 submissions per 7 days
        $userId = $user->getId();
        $cutoff = date('Y-m-d H:i:s', strtotime('-' . self::RATE_LIMIT_DAYS . ' days'));

        $recentCount = DB::table('submissions')
            ->where('submitter_id', $userId)
            ->where('context_id', $context->getId())
            ->where('date_submitted', '>=', $cutoff)
            ->count();

        if ($recentCount >= self::MAX_SUBMISSIONS_PER_WEEK) {
            $errors['rateLimit'] = [__('plugins.generic.submissionPolicy.rateLimitExceeded')];
        }
    }
}
