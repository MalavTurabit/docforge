# 🗄️ MongoDB Collections — Schema Reference

> This page documents the schema structure of every MongoDB collection used in DocForge. Each section shows the collection name, purpose, field descriptions, and a real example document.

---

## Collections Overview

| Collection | Purpose |
|---|---|
| `Departments` | Master list of departments |
| `document_templates` | All document templates with sections & tables |
| `doc_sessions` | Active and completed generation sessions |
| `doc_sections` | Individual AI-generated section content |
| `session_questions` | Questions asked and answers given per section |
| `generated_documents` | Final compiled documents |
| `notion_publishes` | Notion publish history and page URLs |

---

## 1. Departments

**Purpose:** Master list of all departments shown in the DocForge UI department selector.

**Key fields:**
- `_id` — dept ID, used as foreign key across all collections (e.g. `dept_hr`, `dept_it__security`)
- `name` — display name shown in the UI
- `is_active` — controls visibility in the UI

```json
{
  "_id": "dept_hr",
  "name": "Human Resources",
  "is_active": true
}
```

---

## 2. document_templates

**Purpose:** Defines every document template — its sections (AI-written narrative), tables (repeatable blocks), generation rules, and terminology requirements. This is the core config that drives the entire document generation workflow.

**Key fields:**
- `_id` — template ID, format: `dept_{dept_id}_{doc_name_slug}`
- `dept_id` — links to `Departments._id`
- `doc_name` — display name shown in template selector
- `template_json.sections` — narrative sections the AI writes one by one
- `template_json.tables` — repeatable block tables the AI fills
- `template_json.generation_rules` — tone, format, audience settings
- `template_json.terminology_rules` — must-use and forbidden terms
- `header_config.fixed_fields` — document header fields (title, owner, date, etc.)
- `version` — template version number

```json
{
  "_id": "doc_business_operations_market_expansion_assessment_report",
  "dept_id": "dept_business_operations",
  "doc_name": "Market Expansion Assessment Report",
  "version": 1,
  "generation_rules": {
    "output_format": "markdown",
    "tone": "professional analytical",
    "language": "en",
    "audience": "executive leadership",
    "strict_section_order": true,
    "allow_extra_sections": false,
    "determinism_level": "strict"
  },
  "header_config": {
    "fixed_fields": ["Document Title", "Department"],
    "auto_fields": ["Report ID", "Target Market / Region", "Prepared Date", "Prepared By"]
  },
  "template_json": {
    "sections": [
      {
        "id": "executive_summary",
        "title": "Executive Summary",
        "order": 1,
        "required": true,
        "content_type": "narrative",
        "min_words": 80,
        "max_words": 250,
        "min_paragraphs": 1,
        "max_paragraphs": 3,
        "allowed_elements": ["bullets"],
        "style": "concise executive",
        "prompt_hint": "Summarize objective, attractiveness rating, recommendation, and key takeaways",
        "template_text": "",
        "depends_on": [],
        "example_output": ""
      }
    ],
    "tables": [
      {
        "id": "action_plan",
        "title": "Action Plan",
        "required": true,
        "columns": ["Action", "Owner", "Timeline"],
        "min_rows": 2,
        "max_rows": 15,
        "description": "List of actions required for market entry execution"
      }
    ],
    "generation_rules": {
      "output_format": "markdown",
      "tone": "professional analytical",
      "language": "en",
      "strict_section_order": true,
      "allow_extra_sections": false,
      "determinism_level": "strict"
    },
    "terminology_rules": {
      "must_use_terms": ["TAM", "SAM", "SOM", "Go-To-Market"],
      "forbidden_terms": ["guess", "approximate"]
    },
    "variable_definitions": {
      "report_id": {
        "type": "string",
        "required": true,
        "default": "",
        "max_length": 50,
        "allowed_values": [],
        "description": "Unique report identifier"
      }
    },
    "validation_rules": {
      "fail_if_missing_required_sections": true,
      "fail_if_word_limits_violated": true,
      "fail_if_structure_violated": true,
      "strict_variable_usage": true
    }
  },
  "metadata": {
    "created_by": "",
    "created_at": "",
    "updated_at": "",
    "tags": ["market-expansion", "strategy", "assessment"]
  }
}
```

---

## 3. doc_sessions

**Purpose:** Tracks every document generation session — which template, which department, current section progress, and overall status.

**Key fields:**
- `_id` — session ID, format: `sess_{8-char-hex}`
- `dept_id` — links to `Departments._id`
- `template_id` — links to `document_templates._id`
- `status` — `in_progress` | `completed`
- `current_section_index` — which section the user is currently on (0-based)
- `created_at` — session start timestamp
- `completed_at` — null until all sections approved and document compiled

```json
{
  "_id": "sess_test_001",
  "dept_id": "dept_business_operations",
  "template_id": "doc_business_operations_market_expansion_assessment_report",
  "status": "in_progress",
  "current_section_index": 0,
  "created_at": "2026-02-17T12:00:00Z",
  "completed_at": null
}
```

---

## 4. doc_sections

**Purpose:** Stores the AI-generated (and optionally user-edited) content for each section of a session. One document per section per session.

**Key fields:**
- `_id` — section doc ID, format: `sec_{8-char-hex}`
- `session_id` — links to `doc_sessions._id`
- `section_id` — matches `template_json.sections[].id`
- `section_title` — display name of the section
- `content` — final approved markdown content written by AI
- `status` — `generated` | `approved`
- `version` — increments on re-generation
- `created_at` / `updated_at` — timestamps

```json
{
  "_id": "sec_1234ff29",
  "session_id": "sess_34364a17",
  "section_id": "greeting",
  "section_title": "Greeting",
  "version": 1,
  "content": "Dear Malav Joshi,",
  "status": "approved",
  "created_at": { "$date": "2026-02-24T06:20:58.520Z" },
  "updated_at": { "$date": "2026-02-24T06:21:11.470Z" }
}
```

---

## 5. session_questions

**Purpose:** Stores every question the AI asked for a section, the user's answers, and full company context. Used by the AI to generate the section content.

**Key fields:**
- `_id` — format: `sq_{8-char-hex}`
- `session_id` — links to `doc_sessions._id`
- `dept_id` — links to `Departments._id`
- `template_id` — links to `document_templates._id`
- `section_id` — which section these questions belong to
- `section_title` — display name of the section
- `generation_round` — supports re-asking (starts at 1)
- `questions[]` — array of question + answer pairs
  - `question_id` — q1, q2, q3...
  - `question_text` — the AI-generated question
  - `answer` — user's answer
  - `type` — always `text`
  - `is_required` — always `true`
- `company_context` — company name, product, industry, stage, target customer, key problem
- `status` — `questions_generated` | `answers_submitted`
- `created_at` / `updated_at` — timestamps

```json
{
  "_id": "sq_c718c549",
  "session_id": "sess_adf9d86e",
  "dept_id": "dept_product_management",
  "template_id": "doc_product_management_product_strategy_brief",
  "section_id": "market_landscape",
  "section_title": "Market Landscape",
  "generation_round": 1,
  "questions": [
    {
      "question_id": "q1",
      "question_text": "What are the primary market segments currently adopting this product?",
      "answer": "AI startups, chatbot builders, and agent developers.",
      "type": "text",
      "is_required": true
    },
    {
      "question_id": "q2",
      "question_text": "What specific pain points do developers face today?",
      "answer": "Hard to detect, store, and use emotions properly.",
      "type": "text",
      "is_required": true
    }
  ],
  "company_context": {
    "company_name": "Acme Corp",
    "product_name": "rootmotion",
    "product_description": "Gives LLM agents emotional context",
    "industry_vertical": "DevTools",
    "company_stage": "Early Stage / Startup",
    "target_customer": "Developers / Technical users",
    "key_problem_solved": "Provides emotion context to LLM agents"
  },
  "status": "answers_submitted",
  "created_at": { "$date": "2026-02-23T11:49:22.989Z" },
  "updated_at": { "$date": "2026-02-23T11:50:50.078Z" }
}
```

---

## 6. generated_documents

**Purpose:** Stores the final compiled document after all sections are approved and the user clicks "Compile". Used for PDF generation and Notion publishing.

**Key fields:**
- `_id` — format: `doc_{8-char-hex}`
- `session_id` — links to `doc_sessions._id`
- `doc_title` — user-facing document title
- `compiled_content` — full markdown string, sections separated by `\n\n---\n\n`
- `created_at` — compile timestamp

```json
{
  "_id": "doc_6f2e6922",
  "session_id": "sess_d5053824",
  "doc_title": "Financial Risk Assessment",
  "compiled_content": "## Assessment Overview\n\n**Assessment Name:** TRIDENT TECHNOLOGIES Financial Risk Assessment\n\n---\n\n## Financial Scope\n\n**Business Unit(s):**\n- Product Engineering & Platform Development\n- Sales & Business Development\n\n---\n\n## Risk Categories Reviewed\n\n| Risk Category | Current Status | Notes |\n|---|---|---|\n| Liquidity Risk | Low | Stable operating cash flow |",
  "created_at": { "$date": "2026-03-11T07:31:59.575Z" }
}
```

---

## 7. notion_publishes

**Purpose:** Records every time a document is published to Notion — tracks version, Notion page ID, and direct URL. Used to auto-increment version numbers and return the "Open in Notion →" link in the UI.

**Key fields:**
- `_id` — MongoDB ObjectId (auto-generated)
- `session_id` — links to `doc_sessions._id`
- `doc_title` — title of the published document
- `version` — `v1`, `v2`, etc. — auto-increments per session
- `notion_page_id` — Notion page UUID
- `notion_url` — direct URL to the published Notion page
- `published_at` — publish timestamp

```json
{
  "_id": { "$oid": "69b283912052d9cbe68401e2" },
  "session_id": "sess_77b9f3df",
  "doc_title": "Churn & Retention Analysis",
  "version": "v1",
  "notion_page_id": "32161ecb-2bd2-81e4-a024-e56afcce7c28",
  "notion_url": "https://www.notion.so/Churn-Retention-Analysis-32161ecb2bd281e4a024e56afcce7c28",
  "published_at": { "$date": "2026-03-12T09:12:49.403Z" }
}
```

---

## Collection Relationships

```
Departments._id
    └── document_templates.dept_id
    └── doc_sessions.dept_id
    └── session_questions.dept_id

document_templates._id
    └── doc_sessions.template_id
    └── session_questions.template_id

doc_sessions._id  (session_id)
    └── doc_sections.session_id
    └── session_questions.session_id
    └── generated_documents.session_id
    └── notion_publishes.session_id
```
