# Productization Report: Evidence-First AI Workflow Suite

Date: 2026-08-07

## Executive Positioning

The strongest commercial direction is not to sell these projects as separate AI toys. The stronger thesis is to sell a connected family of evidence-first workflow systems for people who drown in documents, emails, rubrics, attachments, decisions, compliance trails, and repeatable admin work.

The unifying product idea:

```text
Client request or file intake
-> evidence extraction
-> structured analysis
-> human review gate
-> packaged deliverable
-> invoice/payment/delivery
-> learning and audit trail
```

This is the same pattern already visible in Evidex, HOMS, VAMP, Outlook Triage, and parts of Sophia. The business should make that pattern explicit and turn it into a reusable core platform.

Recommended umbrella name:

```text
KnowEdge Evidence Automation Suite
```

Recommended positioning:

```text
AI-assisted workflow systems for academics, educators, HR teams, consultants, NGOs,
and evidence-heavy professionals who need structured outputs they can review,
trust, and send.
```

The important distinction: the suite does not claim to replace human judgment. It prepares the evidence, drafts the output, fills the review bundle, and makes the next action easier.

## Core Platform Thesis

Across the projects, the same reusable engine keeps appearing:

```text
Intake
-> normalize files/messages
-> classify intent/risk/task
-> extract evidence
-> map evidence to a framework
-> generate reviewable artifact
-> create delivery pack
-> optionally invoice/paygate/send
-> log every decision
```

That should become the shared infrastructure layer.

Suggested internal name:

```text
AutoRelease Core
```

AutoRelease Core should provide:

- Folder watchers and upload intake.
- Email and form intake.
- Job creation and tracking.
- Document parsing for PDF, DOCX, XLSX, CSV, TXT, ZIP, and email exports.
- Evidence extraction and source provenance.
- Deterministic routing before LLM calls.
- LLM prompt registry and prompt versions.
- Structured output schemas.
- Validation gates.
- Human approval queues.
- Deliverable packaging.
- Invoice/payment gate.
- Delivery email drafts or webhooks.
- Learning logs and outcome review.

This core would let each project become a vertical product module instead of a separate island.

## Portfolio Architecture

The recommended system map:

```text
Outlook Triage / Forms / Drive / File Drop
        |
        v
AutoRelease Core
        |
        +-- HOMS: assignment marking and exam generation
        |
        +-- VAMP: HR/performance evidence review
        |
        +-- Evidex: grant/audit/compliance evidence packs
        |
        +-- Sophia: academic review and research integrity workbench
        |
        +-- NicheFoundry: content/research/marketing production
        |
        +-- Merger: research synthesis and audit mode
        |
        +-- Hivenance: decision governance and evaluation harness
        |
        +-- Arda/Seraph/BEAST: deep governance/security/runtime IP
```

The best commercial story is simple:

```text
Send us the messy batch. We return the reviewed package.
```

Then each product defines what "messy batch" and "reviewed package" mean.

## Product Ranking

### 1. HOMS / Smart Assessor

Commercial priority: highest.

Primary offer:

```text
Send a batch of assignments, the rubric/memo, and the mark sheet.
Receive draft feedback, annotated files, rubric-aligned scoring, and a collated marks file.
```

Best target market:

- School teachers with large marking loads.
- University lecturers.
- Tutors and assistant markers.
- Departments handling repeated formative assessment.
- Private education providers.
- Homeschool and distance learning providers.

Technical strengths:

- Bulk ZIP intake.
- Rubric and memo parsing.
- PDF/DOCX extraction.
- GPT-based assessment.
- Red-text annotations.
- Rubric output.
- Grade CSV update.
- Group member detection.
- Exam builder.
- Job progress.
- MongoDB persistence.

Commercial strength:

The pain is obvious. Marking is slow, repetitive, and mentally expensive. The user does not need to understand AI. They understand "send batch, get feedback pack."

Recommended product package:

```text
HOMS Marking Desk
```

Suggested pitch:

```text
HOMS gives lecturers and teachers an AI-assisted first-pass marking desk.
You upload the batch, memo, rubric, and mark sheet. HOMS prepares feedback,
rubric scoring, annotated files, and a return-ready mark record. The educator
stays in control and approves the final judgment.
```

What it needs next:

- Fix known rubric/essay matrix parsing edge cases.
- Stabilize background task handling.
- Harden bulk upload error recovery.
- Add lecturer review dashboard for score changes.
- Add "confidence and risk" indicators per submission.
- Add a clear disclaimer that outputs are first-pass drafts.
- Add per-institution marking templates.
- Add export presets for eFundi/LMS return formats.
- Create a demo dataset with fake student submissions.
- Create one polished workflow video.

Pricing ideas:

- Per batch: R250 to R1500 depending on size.
- Per script/submission: R5 to R25 for draft marking support.
- Department package: R3000 to R15000 per month.
- Exam builder add-on: R500 to R2500 per paper set.

### 2. VAMP

Commercial priority: very high.

Primary offer:

```text
Turn task agreements, performance agreements, and scattered evidence into
a structured performance review snapshot.
```

Best target market:

- University academic staff.
- Department heads.
- HR administrators.
- Performance review coordinators.
- Professionals needing evidence-backed annual review files.
- Managers who need staff evidence collation without heavy enterprise software.

Technical strengths:

- Task Agreement parsing.
- Performance Agreement management.
- Evidence ingestion across PDF, DOCX, XLSX, PPTX, TXT.
- Deterministic scoring and KPA routing.
- Evidence aggregation.
- PA report generation.
- Offline and web GUI.
- Tests for parsing, scoring, aggregation, and import flows.
- Outlook evidence collection plan already defined.

Commercial strength:

VAMP is evidence-heavy, niche, and defensible. It is not a generic "AI HR assistant." It is a structured performance evidence engine.

Recommended product package:

```text
VAMP Performance Evidence Desk
```

Suggested pitch:

```text
VAMP helps staff and managers convert messy performance evidence into a
reviewable performance snapshot. It reads agreements, maps evidence to
expectations, highlights gaps, and produces a structured review pack.
```

What it needs next:

- Complete Outlook evidence collector integration.
- Build "selected month" and "incomplete task" evidence searches.
- Add a simple evidence confidence score.
- Separate "candidate evidence" from "accepted evidence."
- Add review actions: accept, reject, assign to KPA, assign to task.
- Add redaction controls for sensitive email content.
- Create a clean demo using fake academic staff data.
- Polish the landing page away from cheap one-off wording if selling to institutions.

Pricing ideas:

- Individual annual review pack: R400 to R1500.
- Department setup: R5000 to R25000.
- Monthly evidence maintenance: R500 to R3000 per staff member or small team.
- Institution pilot: R15000 to R60000 depending on scope.

### 3. Evidex

Commercial priority: high, fastest cash path.

Primary offer:

```text
Upload grant/reporting evidence. Receive a structured evidence and compliance pack.
```

Best target market:

- NGOs.
- Grant consultants.
- Monitoring and evaluation teams.
- Small consultancies.
- Audit preparation teams.
- SMEs with compliance reporting obligations.
- Research grant administrators.

Technical strengths:

- Evidence Pack Engine.
- Google Form and Drive-style intake.
- Folder watcher.
- Structured output pack.
- Delivery ZIP.
- Invoice and payment-gating concepts.
- KPI-to-proof-to-source mapping.
- Deterministic workflow possible even without heavy AI.

Commercial strength:

Evidex is the cleanest "done-for-you" service. It does not require users to change their organization. They submit evidence and receive a pack.

Recommended product package:

```text
Evidex Evidence Pack Service
```

Suggested pitch:

```text
Evidex turns scattered project evidence into a ready-to-review grant,
audit, or compliance pack. Upload files, email threads, reports, and proof
documents. Evidex organizes the material into a structured evidence table,
narrative, source list, and delivery bundle.
```

What it needs next:

- Build a clean web intake form.
- Standardize output templates.
- Add source hash/provenance metadata.
- Add a reviewer checklist.
- Add optional client approval before final delivery.
- Add Stripe/PayFast or manual invoice gate.
- Add Google Drive and email delivery automation.
- Add package tiers.

Pricing ideas:

- NGO pack: R2500 to R9000.
- Corporate compliance pack: R9000 to R25000.
- Consultant reseller batch pricing: R1500 to R5000 per pack.
- Monthly retainer: R3000 to R20000 depending on volume.

### 4. KnowEdge Outlook Triage

Commercial priority: high as a front-door product, medium as a standalone product.

Primary offer:

```text
Draft-only inbox triage, risk classification, evidence notes, and reply drafts
for academic/admin workflows.
```

Best target market:

- Lecturers.
- Administrative staff.
- Department coordinators.
- HR staff.
- Consultants.
- Small business owners.
- Anyone handling sensitive inbox workflows with repeated decisions.

Technical strengths:

- Local-first.
- Draft-only.
- `.eml`, `.msg`, Outlook COM, Graph, and Outlook Web Playwright ingestion.
- Deterministic urgency/intent/risk classification.
- Safe-send gate.
- Primary, safer, and shorter draft variants.
- SQLite, JSONL, CSV, dashboard, run bundle, closeout summary.
- GUI and CLI.
- MSI installer scaffolding.
- Smoke test passes.

Commercial strength:

The real value is not "it sends email." The value is that it protects attention, prepares responses, produces evidence notes, and routes work into the rest of the suite.

Recommended product package:

```text
KnowEdge Inbox Desk
```

Suggested pitch:

```text
KnowEdge Inbox Desk reviews email exports or Outlook messages locally,
classifies urgency and risk, drafts safe response options, and creates
auditable evidence notes. It never sends on its own. You stay in control.
```

Best integration flows:

```text
Outlook -> HOMS
Lecturer receives marking batch -> Triage classifies -> HOMS job created -> return email drafted.
```

```text
Outlook -> VAMP
Performance-related email -> evidence candidate -> mapped to KPA/task -> accepted into VAMP.
```

```text
Outlook -> Evidex
Grant/reporting thread -> attachments extracted -> evidence pack job created.
```

```text
Outlook -> Sophia
Student/supervisor research thread -> reading/referencing task -> academic review workspace.
```

What it needs next:

- Decide commercial ingestion mode.
- Prefer `.eml`, Outlook COM, Graph, and user-approved local export for clients.
- Treat browser automation as power-user/internal unless consent and reliability are clear.
- Add one-click "create HOMS/VAMP/Evidex/Sophia job" actions.
- Add project/folder routing rules.
- Add redaction before logs.
- Add POPIA/GDPR privacy notes.
- Add config wizard for institutions.
- Add "no auto-send" prominently.

Pricing ideas:

- Individual setup: R500 to R1500.
- Monthly support: R150 to R500.
- Academic/admin package: R1000 to R5000 per month.
- Department workflow setup: R5000 to R25000.

### 5. Sophia

Commercial priority: medium-high, long-term trust product.

Primary offer:

```text
Academic review, referencing support, source-fit analysis, and integrity-preserving research feedback.
```

Best target market:

- Postgraduate students.
- Honors and master's students.
- Doctoral candidates.
- Supervisors.
- Writing centers.
- Research methods lecturers.
- Academic development offices.

Technical strengths:

- Authorship-preserving academic assistance.
- Evidence-bounded review.
- Strong governance language.
- Research workbench.
- Academic integrity positioning.
- Useful as a review layer rather than a ghostwriter.

Commercial strength:

The market is large, but risky. The product must never be sold as "write my thesis." It should be sold as "review my argument, references, source fit, structure, and evidence trail."

Recommended product package:

```text
Sophia Academic Review Desk
```

Suggested pitch:

```text
Sophia helps students and researchers review their academic work without
replacing their authorship. It checks argument structure, source alignment,
referencing quality, evidence use, and revision priorities.
```

What it needs next:

- Create strict "not ghostwriting" UX.
- Add citation/source verification workflow.
- Add Zotero or BibTeX import/export.
- Add review categories: argument, method, source fit, referencing, clarity.
- Add supervisor-friendly summary output.
- Add student consent and academic integrity notice.
- Add before/after review demo using public sample text.
- Add pricing packages by document length.

Pricing ideas:

- Student review: R150 to R800 per chapter/article depending on length.
- Postgrad monthly support: R300 to R1200.
- Writing center pilot: R5000 to R30000.
- Supervisor/research group package: R1500 to R8000 per month.

### 6. NicheFoundry

Commercial priority: medium externally, high internally.

Primary offer:

```text
Faceless content and niche research production system.
```

Best target market:

- Internal use for your own marketing.
- Small businesses needing research-backed content.
- Educators creating explainer content.
- Consultants building niche authority.
- YouTube automation clients, with caution.

Technical strengths:

- Research/opportunity analysis.
- Script and visual planning.
- Narration and rendering pipeline.
- Compliance/provenance ideas.
- Private upload path.

Commercial strength:

This is best used as the growth engine for the rest of the suite before being sold directly. Let it produce HOMS, VAMP, Evidex, and Sophia content.

Recommended product package:

```text
NicheFoundry Growth Desk
```

Suggested pitch:

```text
NicheFoundry turns niche research into structured content packs:
topics, scripts, visuals, narration plans, and publishing-ready assets.
```

What it needs next:

- Use it internally first.
- Build a repeatable campaign template per product.
- Add human editorial review.
- Add lead magnet generation.
- Add landing page copy generation.
- Add analytics feedback loop.
- Avoid selling "passive income automation" as the main claim.

Pricing ideas:

- Content pack: R500 to R3000.
- Monthly content engine: R3000 to R15000.
- Internal value: lead generation for the full suite.

### 7. Merger

Commercial priority: low as standalone, useful as a module.

Primary offer:

```text
Research synthesis and audit mode for Sophia and HOMS.
```

Best target market:

- Postgraduate supervisors.
- Research integrity reviewers.
- Academic departments.
- Students needing synthesis review.

Technical strengths:

- Tri-artifact synthesis.
- Local-first content analysis.
- Screening, style, and similarity ideas.
- Audit bundle concept.

Commercial weakness:

As a standalone product it is too abstract. It becomes valuable when folded into Sophia as a "research synthesis audit" or into HOMS as a "student submission synthesis/review mode."

Recommended product package:

```text
Sophia Research Audit Mode
```

What it needs next:

- Replace mock retrieval/rerank components.
- Define exact input/output templates.
- Add citation verification.
- Add supervisor-facing report format.
- Fold into Sophia rather than sell separately.

### 8. Hivenance

Commercial priority: low as trading, medium-high as internal governance.

Primary offer:

```text
Governed decision pipeline and evaluation harness.
```

Best use:

- Internal research pipeline.
- Gate evaluation engine.
- Canary/shadow testing infrastructure.
- Evidence and decision logging across products.

Commercial weakness:

The trading pivot did not show reliable enough performance to sell. But the architecture has useful ideas: observe, hypothesize, test, evaluate, promote only repeatable patterns, log outcomes.

Recommended role:

```text
Use Hivenance as the suite's internal decision lab.
```

What it needs next:

- Remove trading-first language from shared components.
- Extract reusable evaluation patterns.
- Build "hypothesis -> observation -> execution -> outcome" logs for non-trading workflows.
- Use it to evaluate prompts, routing rules, and business process outcomes.

### 9. Arda / Seraph / BEAST

Commercial priority: later-stage, deep IP.

Primary offer:

```text
Governed AI runtime, secure tool execution, evidence-backed agent operations,
and policy-controlled automation.
```

Best target market:

- AI engineering teams.
- Security-conscious dev shops.
- Research labs.
- Internal governance buyers.
- Technical founders.

Technical strengths:

- Kernel/substrate governance concepts.
- Tool gateway integrations.
- Runtime policy enforcement.
- Agent editing/runtime layer.
- Verification and rollback evidence.
- Strong "AI may advise, substrate decides" philosophy.

Commercial weakness:

Harder sale. The buyer needs deep technical trust and a bigger budget. It should support the other products first, then become its own platform later.

Recommended role now:

```text
Use this as the trust and governance spine underneath the suite.
```

What it needs next:

- Package a smaller developer-facing demo.
- Create clean architecture diagrams.
- Separate research claims from observed proof.
- Add simple examples: policy gate, tool approval, patch verification, rollback.
- Avoid leading with kernel/security depth for non-technical buyers.

## Best Cross-Product Bundles

### Bundle A: Lecturer Relief Stack

Products:

- HOMS.
- KnowEdge Outlook Triage.
- Sophia optional.

Workflow:

```text
Lecturer receives student/admin emails
-> Outlook Triage flags assessment items
-> HOMS processes assignments
-> Sophia helps review academic feedback quality
-> lecturer approves outputs
```

Buyer:

- Individual lecturers.
- Academic departments.
- Private education providers.

Core pitch:

```text
Reduce marking and admin drag without surrendering academic judgment.
```

### Bundle B: Performance Evidence Stack

Products:

- VAMP.
- Outlook Triage.
- Evidex optional.

Workflow:

```text
Task agreement + performance agreement
-> Outlook evidence collection
-> file evidence ingestion
-> KPA/task mapping
-> review snapshot
-> final performance pack
```

Buyer:

- University staff.
- HR.
- Department managers.

Core pitch:

```text
Stop hunting for performance proof at the end of the year.
```

### Bundle C: Grant and Compliance Pack Stack

Products:

- Evidex.
- Outlook Triage.
- NicheFoundry optional for report narratives and public updates.

Workflow:

```text
Google Form / Drive / Outlook / file drop
-> evidence extraction
-> KPI-to-proof mapping
-> compliance pack
-> invoice/paygate
-> delivery email
```

Buyer:

- NGOs.
- Grant consultants.
- M&E consultants.
- Small compliance teams.

Core pitch:

```text
Turn scattered proof into a structured funder-ready evidence pack.
```

### Bundle D: Postgraduate Support Stack

Products:

- Sophia.
- Merger as research audit mode.
- Outlook Triage optional for supervisor/student correspondence.

Workflow:

```text
Draft chapter / article / proposal
-> source and citation review
-> argument and methodology review
-> integrity-safe feedback
-> revision plan
```

Buyer:

- Students.
- Supervisors.
- Writing centers.
- Research offices.

Core pitch:

```text
High-level academic feedback without outsourcing authorship.
```

## Technical Integration Plan

### Shared Job Model

All products should use a common job envelope:

```json
{
  "job_id": "uuid",
  "client_id": "client-or-demo-id",
  "product": "homs|vamp|evidex|sophia|nichefoundry",
  "source": "outlook|drive|form|file_drop|manual",
  "status": "received|processing|needs_review|approved|delivered|blocked",
  "inputs": [],
  "outputs": [],
  "audit": [],
  "billing": {
    "invoice_id": null,
    "payment_status": "not_required|pending|paid"
  }
}
```

### Shared Evidence Model

All evidence-heavy products need the same evidence record:

```json
{
  "evidence_id": "stable-hash",
  "job_id": "uuid",
  "source_type": "email|attachment|document|spreadsheet|form",
  "source_path": "local-or-cloud-ref",
  "title": "visible title",
  "date_observed": "iso-date",
  "text_extract": "bounded text",
  "hash": "sha256",
  "claims": [],
  "mapped_to": [],
  "confidence": 0.0,
  "review_status": "candidate|accepted|rejected|needs_review"
}
```

### Shared Gate Model

Every product should have the same decision posture:

```text
green: routine, ready for review
amber: needs human approval
red: blocked or sensitive
```

This fits HOMS, VAMP, Evidex, Sophia, and Outlook.

### Shared LLM Safety Rules

The suite should standardize these rules:

- LLM outputs must be structured and schema-validated.
- Prompts must be versioned.
- Every output needs source references or explicit uncertainty.
- Sensitive actions require human approval.
- No autonomous sending.
- No fabricated citations.
- No final academic grading without educator approval.
- No HR/performance decision without manager/user approval.
- No compliance claims without evidence mapping.

## What Each Project Needs To Become Sellable

### HOMS needs:

- A demo dataset.
- A polished upload-to-output workflow.
- Review UI for accepting/changing marks.
- Better rubric parser robustness.
- Institution-specific export presets.
- Clear "educator approves final marks" positioning.

### VAMP needs:

- Outlook evidence collector wired into the main evidence pipeline.
- Candidate evidence staging.
- Month and task filters.
- A cleaner landing page.
- Redaction and privacy controls.
- A fake but realistic demo performance pack.

### Evidex needs:

- Clean intake form.
- Pack templates.
- Payment/invoice gate.
- Delivery automation.
- Provenance hashes.
- A 48-hour service offer landing page.

### Outlook Triage needs:

- Decide safe commercial ingestion path.
- Add route-to-product buttons.
- Add redaction.
- Add config wizard.
- Add stable packaged Windows build.
- Add demo mode with fake inbox.

### Sophia needs:

- Strict academic integrity UX.
- Citation verification.
- Zotero/BibTeX support.
- Report templates.
- Student and supervisor pricing.
- Avoid any ghostwriting positioning.

### NicheFoundry needs:

- Internal product campaigns first.
- Template packs for each product.
- Analytics feedback.
- Human editorial approval.

### Merger needs:

- Fold into Sophia.
- Replace mocks.
- Define exact report outputs.

### Hivenance needs:

- Extract governance/evaluation ideas.
- Remove trading language where reused.
- Use as internal evaluation harness.

### Arda/Seraph/BEAST need:

- A smaller developer demo.
- Clean claims discipline.
- Architecture diagrams.
- Proof bundles.
- Later-stage enterprise packaging.

## Go-To-Market Strategy

### Phase 1: Sell Services, Not Software

Do not start by asking clients to install a platform.

Start with done-for-you workflows:

```text
Send us the files. We return the pack.
```

Best first offers:

1. HOMS marking support pack.
2. Evidex evidence pack.
3. VAMP performance snapshot.
4. Outlook triage setup for lecturers/admin staff.

Why:

- Easier to explain.
- Lower buyer friction.
- Lets you learn real client needs.
- Lets you charge before the product is perfect.
- Avoids enterprise procurement at the start.

### Phase 2: Turn Repeat Work Into Productized Packages

After 5 to 10 real service runs, productize:

- Standard intake form.
- Standard output pack.
- Standard price.
- Standard delivery timeline.
- Standard review disclaimer.
- Standard demo video.

### Phase 3: Sell Department Pilots

Once there are examples:

- Approach departments.
- Offer a controlled pilot.
- Limit scope.
- Use fake/demo data until trust is earned.
- Keep human approval central.

### Phase 4: Package Software

Only after the service proves demand:

- Installer.
- Hosted dashboard.
- User management.
- Templates.
- Support plan.
- Billing.

## First 30-Day Execution Plan

### Week 1

- Create one umbrella landing page for KnowEdge Evidence Automation Suite.
- Create four product pages: HOMS, VAMP, Evidex, Outlook Triage.
- Build demo outputs for each with fake data.
- Produce one PDF sample pack per product.

### Week 2

- Build the shared intake form.
- Add routing options:
  - Marking batch.
  - Performance evidence.
  - Grant/compliance pack.
  - Inbox triage.
  - Academic review.
- Add manual invoice/payment instructions.
- Add a delivery template.

### Week 3

- Contact 20 lecturers/teachers.
- Contact 10 NGOs/consultants.
- Contact 10 academic staff/HR-type users.
- Offer discounted pilot packs.
- Collect objections and revise.

### Week 4

- Turn the best-performing offer into a sharper package.
- Create a case-study-style demo.
- Add pricing.
- Add FAQ.
- Start using NicheFoundry to publish weekly content around the strongest pain.

## Recommended First Public Offers

### Offer 1: Marking Relief Pack

```text
For teachers and lecturers with assignment backlogs.
Send the assignment batch, rubric/memo, and mark sheet.
Receive draft feedback, suggested marks, annotated files, and a collated marks file.
Educator approval remains required.
```

### Offer 2: Performance Evidence Snapshot

```text
For academic and admin staff preparing performance reviews.
Send your agreement and evidence folder.
Receive a mapped evidence snapshot, gaps list, and review-ready report.
```

### Offer 3: Grant Evidence Pack

```text
For NGOs and consultants preparing reports.
Send project evidence and reporting requirements.
Receive a structured evidence table, source list, narrative, and delivery pack.
```

### Offer 4: Inbox Control Desk

```text
For overloaded professionals.
Export or connect approved Outlook messages.
Receive urgency/risk triage, reply drafts, evidence notes, and a daily closeout.
No automatic sending.
```

## The Honest Bet

The crypto system was trying to extract value from a noisy market. This suite is different. These projects extract value from real operational pain:

- People hate marking backlogs.
- People hate performance evidence collation.
- NGOs hate compliance reporting.
- Academics need careful research feedback.
- Professionals drown in email.

That is a better market because the user can immediately feel the pain and immediately understand the deliverable.

The strongest move is to stop thinking "Which one app wins?" and start thinking:

```text
Which repeatable evidence workflow can I sell this week?
```

The answer is probably:

1. HOMS for marking.
2. Evidex for evidence packs.
3. VAMP for performance evidence.
4. Outlook Triage as the intake/router that makes all three smoother.

## Final Recommendation

Build the suite around three principles:

```text
Evidence in.
Human judgment preserved.
Review-ready pack out.
```

Lead with HOMS, VAMP, and Evidex because they have obvious business pain and concrete deliverables. Use Outlook Triage as the front door. Use Sophia as the academic integrity branch. Use NicheFoundry as the marketing engine. Use Hivenance and Arda/Seraph/BEAST as internal governance and infrastructure until they are packaged enough for technical buyers.

This is not one product. It is a workflow automation studio with a common evidence engine underneath it.

