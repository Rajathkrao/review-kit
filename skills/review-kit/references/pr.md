# PR mode

Sources: Anthropic code-review (eligibility check, PR summary, prior-PR comments, link format,
gh-only interaction, re-check before posting), superpowers receiving-code-review (judging review
feedback, thread replies), pr-review-toolkit review-pr (aggregate by severity).

Requires `gh` authenticated for github.com (`gh auth status`). If it isn't, say so and offer to
review the local branch instead.

## 1. Eligibility

From `$PKG/pr.json`: if the PR is closed or merged, ask whether to continue. If it's a draft,
continue but say so. If it is an automated PR (dependency bot), switch the lens set to the
dependency checks in the `standards` lens (changelog, one dependency per change, lockfile).

## 2. Purpose

The PR body and linked issues (`closingIssuesReferences`) are contract candidates alongside any
ADR/spec in the repo. Follow `intake.md`. The PR description is a claim about the change; verify
it against the diff.

## 3. Review

Run `deep` lenses (or `quick` with `--quick`) on the PR diff from the package. Use the PR head
SHA for every link.

## 4. Existing review comments

`$PKG/pr-comments.json` holds review threads (inline comments with path/line, resolved state)
and top-level reviews/comments. For each unresolved, substantive comment by a human or bot,
apply the receiving-code-review checks:

1. Is it technically correct for this codebase?
2. Would following it break existing functionality?
3. Is there a reason for the current implementation (contract, ADR, comment, git history)?
4. Does the reviewer have the full context?
5. YAGNI: if it asks to "implement properly", is the thing actually used? (grep for callers)

Verdicts: **Valid, unaddressed** / **Valid, addressed in a later commit** (cite it) /
**Push back** (technical reason) / **Needs author context** (what to ask). Skip resolved threads,
pure approvals, and CI bot noise. If a comment duplicates one of your findings, merge them and
credit the comment. A "Valid, unaddressed" comment your lenses missed is not re-posted as a new
inline comment (it's already on the PR); the review summary endorses it in one line instead
("Agree with @alice on src/export.ts:13: <why>"). It never blocks posting.

Put the table in the report's "Existing PR comments" section, and add the endorsed ones to
`$PKG/findings.json` as `"endorsed_comments": [{"author", "where", "why"}]` so the posted summary includes them.

## 5. Posting (only with --post, only after confirmation)

1. Re-check eligibility (the PR may have closed or received new commits while you reviewed). If
   the head SHA changed, say so and offer to re-run.
2. Build the payload without sending it:
   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/post_review.py" "$PKG"
   ```
   It maps each finding to a line in the PR diff, puts findings outside the diff into the summary
   body, and writes `$PKG/review-payload.json` plus a preview at `$PKG/review-preview.md`.
3. Show the preview. Ask: Post as shown / Edit first / Don't post.
4. On "Post": `python3 "${CLAUDE_SKILL_DIR}/scripts/post_review.py" "$PKG" --submit`. This
   creates one review with event `COMMENT` and inline comments. Report the review URL.
5. Replies to existing threads (from step 4 verdicts) are opt-in: offer them separately, show
   each reply text, and post with `--reply <comment_id> --body-file <file>` only for the ones
   the user approves. Reply text states the technical point only, without performative
   agreement or thanks (receiving-code-review).

Non-interactive with `--post`: post the review as built (the flag is the consent) without asking, never thread replies.
