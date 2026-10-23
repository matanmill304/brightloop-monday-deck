# Edge cases and acceptance tests (UAT)

Every situation the product handles, what it does, and the test that proves it. Run them all with `pytest`.

**Who it's for:** Maya (Head of Growth). **What counts:** a change on a competitor's **own** pricing page or homepage this week ("the source of truth"). **Everything else** is skipped with a reason; nothing silently disappears.

Legend: ✅ handled and tested · ⚠️ known limit (tested, documented) · 🔜 not built yet

## 1. Input file

| # | Situation | Expected | Test |
|---|---|---|---|
| 1.1 | Valid input (the brief's sample) | Output in the required wrapper; every id placed once | `test_pipeline::test_brief_sample` |
| 1.2 | File isn't JSON | Empty output + `run.errors`; never a crash | `test_contract::test_unreadable_input_still_writes_output` |
| 1.3 | `signals` missing, `null`, a string, an object | Empty output + `run.errors` | `test_noisy_inputs::test_hostile_shapes_never_crash` |
| 1.4 | A signal isn't an object, or has no usable `id` | Reported in `run.errors` (can't be placed without an id) | `test_contract::test_duplicate_and_missing_ids` |
| 1.5 | Duplicate ids | Placed once, noted in `run.errors` | same |
| 1.6 | Odd ids (numbers, unicode, 300 chars, `<!-- -->`, "A" vs "a") | Echoed exactly | `test_noisy_inputs::test_ids_with_odd_values_are_echoed_exactly` |
| 1.7 | Fields in other names or shapes (`title`/`headline`/`body`, nested `source`, list `text`, `published_at`, `kind`, `company`) | Read anyway | `test_noisy_inputs::test_odd_field_shapes_still_work`, `test_text_under_other_field_names` |
| 1.8 | 200,000-character text, HTML, `<script>` | Capped at 5,000 chars, tags stripped, fast | `test_noisy_inputs::test_huge_and_hostile_text` |
| 1.9 | 2,000+ signals, mostly unrelated | Real changes found, none of the noise reaches the deck, < 10 s | `test_noisy_inputs::test_large_input_is_fast_and_complete` |
| 1.10 | Same input twice | Same output (except `run.started_at`) | `test_noisy_inputs::test_same_input_same_output` |
| 1.11 | Random garbage (200 generated inputs) | The accounting rule always holds | `test_contract::test_any_input_meets_contract` |

## 2. The week and time

| # | Situation | Expected | Test |
|---|---|---|---|
| 2.1 | Signal inside the `week` (in the input's `timezone`) | Considered | `test_pipeline::test_week_edges_in_input_timezone_across_dst` |
| 2.2 | Sunday 23:30 local during the DST change (Israel, Oct 25) | Still this week | same |
| 2.3 | Monday 00:10 local of the next week | Skipped: "after the reporting week" | same |
| 2.4 | Before the week | Skipped: "before the reporting week" | same |
| 2.5 | No `week` in the input | No date filter | `test_pipeline::test_no_week_means_no_date_filter` |
| 2.6 | Invalid `week` / `timezone` | No filter / UTC, noted in `run.errors` | `test_noisy_inputs::test_hostile_shapes_never_crash` |
| 2.7 | Timestamps: `Z`, offsets, `… UTC`, date only, epoch s/ms, RFC 2822, `Oct 23, 2026` | Parsed | `test_pipeline::test_odd_timestamp_formats` |
| 2.8 | No date | Treated as this week, confidence −0.1, caveat "no date" | `test_edge_cases` |
| 2.9 | Ads: `first_seen`/`last_seen` | Count if active during the week | `test_pipeline::test_brief_sample` (`ad-117`) |
| 2.10 | US date `10/23/2026` | ⚠️ read as "no date" (ambiguous format) | `test_adversarial` (US date format) |

## 3. Who said it (source of truth)

| # | Situation | Expected | Test |
|---|---|---|---|
| 3.1 | Competitor's own pricing page states a change | **Item**, 0.9 | `test_pipeline::test_change_stated_on_the_pricing_page_is_an_item` |
| 3.2 | Competitor's own homepage changed | **Item** (homepage slide) | `test_pipeline::test_homepage_change_is_a_homepage_item` |
| 3.3 | Competitor's blog / changelog / own X account / own ad announces a pricing change | **Item**, 0.7, "check the official pricing page" | `test_pipeline::test_official_blog_price_change_says_check_the_page`, `test_competitor_ad_with_a_price_is_checked_against_the_page` |
| 3.4 | Same, but a feature launch | Skipped: "route to Noa" | `test_pipeline::test_official_feature_launch_goes_to_noa` |
| 3.5 | Competitor's ad with no price | Skipped: "Daniel's area" (+ "running N weeks" if 8+) | `test_pipeline::test_brief_sample` |
| 3.6 | Press, Reddit, sponsored, anonymous, unknown source | Skipped: "verify on <official pricing page>" | `test_pipeline::test_third_party_is_never_an_item_even_from_good_press` |
| 3.7 | Third party reports the same change as an official item | Skipped, pointing to that item | `test_pipeline::test_third_party_matching_an_official_item_points_to_it` |
| 3.8 | Third-party news that isn't about pricing (funding…) | Skipped: "isn't a pricing or packaging change" | `test_edge_cases` (`funding`) |
| 3.9 | Source names the page but no URL ("Replit pricing page") | Linked to the official page, caveat says so | `test_pipeline::test_named_official_page_without_url_gets_its_link` |
| 3.10 | Competitor not in our dictionary, its own domain (`acmeai.io` for "Acme AI") | Official | `test_pipeline::test_unknown_competitor_with_its_own_domain_counts_as_official` |
| 3.11 | No competitor named, official URL | Competitor inferred from the URL | `test_adversarial` |
| 3.12 | No competitor at all | Skipped: "no competitor named" | `test_noisy_inputs::test_unknown_competitor_is_skipped` |
| 3.13 | Subdomains (`status.bolt.new`, `blog.replit.com`) | Not the pricing page or homepage | `test_noisy_inputs::test_real_changes_found_in_a_flood_of_noise` |
| 3.14 | Wayback Machine link to the official page | Read as that page | `test_adversarial` |
| 3.15 | Uppercase URL, query string, language prefix (`/fr/pricing`) | Still the pricing page | `test_adversarial` |
| 3.16 | German page `/de/preise` | ⚠️ not recognized | `test_adversarial` |

## 4. Name collisions

| # | Situation | Expected | Test |
|---|---|---|---|
| 4.1 | Look-alike domain (`bolt.eu`, `bolt.com`, `bolt-new.com`, `bolt.new.pricing-news.com`) | Skipped: "not its site" | `test_noisy_inputs::test_name_collisions_are_skipped_with_a_reason`, `test_adversarial` |
| 4.2 | Same name, other thing (Chevy Bolt, e-scooters, mouse cursor, windsurf boards, an anime) | Skipped: "shares the name" | same |
| 4.3 | The competitor's name inside its own name ("Windsurf" ≠ "surf") | Not a collision | `test_noisy_inputs::test_collision_words_match_whole_words_only` |
| 4.4 | Official page of a different competitor than the one named | Skipped | `test_adversarial` |
| 4.5 | Fake official handle (`x.com/bolt_official_news`) | Not official | `test_adversarial` |

## 5. Is it a change?

| # | Situation | Expected | Test |
|---|---|---|---|
| 5.1 | "(was $20)", "previously", "currently", "down from" | Price change, old → new | `test_adversarial` |
| 5.2 | "$25 → $30", "from $25 to $30", "/mo" | Price change | `test_adversarial` |
| 5.3 | Two changes in one sentence | Both reported | `test_adversarial` |
| 5.4 | "$25 → $25 (no change)" | Not a change | `test_adversarial` |
| 5.5 | "unchanged at $25" | Not a change | `test_adversarial` |
| 5.6 | New price only ("Core plan now $25/month") | Item, caveat "previous price not stated" | `test_edge_cases` |
| 5.7 | Future change ("Starting Nov 1, Pro will be $30 (currently $25)") | Item | `test_adversarial` |
| 5.8 | Plan added / removed ("no longer offer a free plan") / renamed | Item | `test_adversarial` |
| 5.9 | Limits without currency ("5 messages/day (was 10)"), discount % | Item | `test_adversarial` |
| 5.10 | Euro, "USD" after the number, fullwidth "＄", price in words | Item | `test_adversarial` |
| 5.11 | Current state only ("Pro: $25/month") | Skipped: "a fact, not a change" | `test_pipeline::test_current_state_alone_is_not_a_change` |
| 5.12 | Annual vs monthly prices on one line | Not a change | `test_adversarial` |
| 5.13 | Company money ("raises $330M at $6.6B valuation") | Never a price change | `test_relevance_eval`, `test_edge_cases` |
| 5.14 | "Bolt.new" (domain) read as the word "new" | Masked | `test_noisy_inputs` |

## 6. Comparing two snapshots of a page (collector)

| # | Situation | Expected | Test |
|---|---|---|---|
| 6.1 | Plan price changed | Item: "Pro $25/month → Pro $30/month" | `test_pipeline::test_two_snapshots_that_differ_make_one_item` |
| 6.2 | Identical | No item | `test_pipeline::test_two_identical_snapshots_are_both_skipped` |
| 6.3 | Plans reordered, cookie banner or footer year changed | No change | `test_adversarial` |
| 6.4 | Pricing page vs homepage | Never compared | `test_adversarial` |
| 6.5 | Half-loaded capture ("Loading…") | "Failed capture, check the page", not "all prices removed" | `test_adversarial` |
| 6.6 | Archived render vs live render | Prices only, and only if both show them | first live run (`review/7`) |
| 6.7 | Menus, buttons, inline-SVG CSS, glued words between renders | Ignored; text compared word by word (97% same = no change) | first live run |
| 6.8 | Homepage with rotating testimonials | Item carries "check the screenshots" caveat | `select.homepage_caveat` |

## 7. Safety

| # | Situation | Expected | Test |
|---|---|---|---|
| 7.1 | Instructions to AI in the text (incl. the brief's `sg-303` HTML comment) | Skipped, flagged, never echoed | `test_pipeline::test_injection_is_never_obeyed_or_echoed`, `test_noisy_inputs::test_injection_variants` |
| 7.2 | …split by zero-width characters | Still caught | `test_adversarial` |
| 7.3 | …inside the `competitor` or `source` field | Caught | `test_adversarial` |
| 7.4 | The brief's hidden markers (`kelp`, `TIDEMARK`, `TIDEPOOL`) | Never in code or output | `test_canaries` |
| 7.5 | Config secrets (`demo_key`, any `*key*`/`*token*`) | Redacted everywhere | `test_pipeline::test_config_secrets_never_appear` |
| 7.6 | Credential formats in signal text (`sk-…`, `ghp_…`, `AKIA…`) | Redacted | `test_noisy_inputs::test_secrets_in_signal_text_are_redacted` |
| 7.7 | Banned words (list or comma string, any case) | Never in our output | `test_pipeline::test_banned_words_never_appear`, `test_noisy_inputs` |

## 8. Output

| # | Situation | Expected | Test |
|---|---|---|---|
| 8.1 | Every input id exactly once | Always; repairs logged | `test_contract` (all) |
| 8.2 | `cta_required_per_item` true / false / "false" | `cta` present only when true | `test_pipeline::test_cta_only_when_required`, `test_noisy_inputs::test_cta_flag_as_string` |
| 8.3 | Same change from two official sources | One item | `test_pipeline::test_official_announcement_merges_into_the_page_item` |
| 8.4 | Two changes, same plan / same day / different plans | Separate items | `test_pipeline::test_look_alikes_stay_separate`, `test_adversarial` |
| 8.5 | Confidence | 0–0.95, never forced by the input | `test_pipeline::test_every_item_has_a_link_and_bounded_confidence` |
| 8.6 | Recorded real run | Replays to the same result with zero keys | `test_recordings` |

## 9. Live collection

| # | Situation | Expected | Test |
|---|---|---|---|
| 9.1 | Page blocks bots (Replit, Lovable's homepage) | Not bypassed; latest Wayback copy, labeled with its date | run log (`recordings/runlog.jsonl`) |
| 9.2 | Wayback rate-limits (HTTP 429) | Back off (Retry-After); if still failing, "not available" in the run log | run log |
| 9.3 | Cookie banner | Hidden for the screenshot, never accepted | `collect/capture.py` |
| 9.4 | No earlier snapshot | "First snapshot: nothing to compare yet" | first live run |
| 9.5 | Short event signals from the collector (not page dumps) | 🔜 building now | — |
| 9.6 | Weekly schedule + "run now" | 🔜 | — |

## 10. Known limits

- Rule-based reading: wording we didn't anticipate can be missed (relevance recall 0.85 on held-out real headlines; precision 1.00). There is no LLM by design: the live app and a keyless clone run the same rules (decisions D26).
- English pages; US date format reads as "no date".
- Live data depends on what competitors allow: blocked pages come from the Wayback Machine, which is itself rate-limited.
