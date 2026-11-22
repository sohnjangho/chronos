"""보고서 스키마(월간 · 분기별, 일간 제외)."""

from typing import Literal

from pydantic import BaseModel, Field

Cadence = Literal["monthly", "quarterly"]
BlockKind = Literal["prose", "kpi", "table", "chart", "manual"]
DataBinding = Literal[
    "summary_prose",
    "kpi_summary",
    "wbs_table",
    "milestone_table",
    "s_curve_month",
    "spi_trend",
    "delay_table",
    "lookahead_3w",
    "scenario_compare",
    "manual_input",
]


class TemplateSection(BaseModel):
    id: str = Field(min_length=1, max_length=60)
    heading: str = Field(min_length=1, max_length=160)
    block_kind: BlockKind
    data_binding: DataBinding
    table_columns: list[str] = Field(default_factory=list)
    section_prompt: str = ""


class StyleMemory(BaseModel):
    tone: str = "~습니다 (간결한 보고서 체)"
    date_format: str = "YYYY.MM.DD"
    number_precision: int = Field(default=1, ge=0, le=2)
    header_note: str = ""
    learned_rules: list[str] = Field(default_factory=list)


class TemplateOut(BaseModel):
    id: int | None = None
    builtin_key: str | None = None
    schedule_id: int | None = None
    project_name: str | None = None
    cadence: Cadence
    name: str
    is_default: bool
    is_builtin: bool
    source_file_id: int | None = None
    source_file_name: str | None = None
    sections: list[TemplateSection]
    style: StyleMemory
    created_by: str
    updated_at: str | None = None


class TemplateListOut(BaseModel):
    current_project: list[TemplateOut]
    other_projects: list[TemplateOut]
    builtins: list[TemplateOut]


class TemplateLearnIn(BaseModel):
    file_id: int
    schedule_id: int
    cadence: Cadence | None = None
    name: str | None = None
    auto_save: bool = False


class TemplateLearnOut(BaseModel):
    suggested_name: str
    suggested_cadence: Cadence
    source_file_id: int
    source_file_name: str
    analysis_summary: str
    sections: list[TemplateSection]
    style: StyleMemory
    saved_template: TemplateOut | None = None


class TemplateCreateIn(BaseModel):
    schedule_id: int
    cadence: Cadence
    name: str = Field(min_length=1, max_length=160)
    is_default: bool = True
    source_file_id: int | None = None
    source_file_name: str | None = None
    sections: list[TemplateSection] = Field(min_length=1)
    style: StyleMemory = Field(default_factory=StyleMemory)


class TemplateUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    cadence: Cadence | None = None
    is_default: bool | None = None
    sections: list[TemplateSection] | None = None
    style: StyleMemory | None = None


class TemplateAdoptIn(BaseModel):
    schedule_id: int
    is_default: bool = True
    name: str | None = Field(default=None, min_length=1, max_length=160)


class ReportBlock(BaseModel):
    id: str
    heading: str
    block_kind: BlockKind
    data_binding: DataBinding
    text: str = ""
    metrics: list[dict] = Field(default_factory=list)
    table: dict | None = None
    chart: dict | None = None


class ReportGenerateIn(BaseModel):
    cadence: Cadence
    template_id: int | None = None
    use_builtin: bool = False
    period_label: str | None = Field(default=None, max_length=60)
    title: str | None = Field(default=None, max_length=200)
    extra_note: str = ""


class ReportUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    period_label: str | None = Field(default=None, min_length=1, max_length=60)
    status: Literal["draft", "final"] | None = None
    blocks: list[ReportBlock] | None = None


class ReportRegenerateIn(BaseModel):
    template_id: int | None = None
    use_builtin: bool = False
    extra_note: str = ""


class ReportReviseIn(BaseModel):
    block_id: str
    instruction: str = Field(min_length=1, max_length=500)
    remember_rule: bool = False


class ReportSummaryOut(BaseModel):
    id: int
    schedule_id: int
    template_id: int | None
    template_name: str
    cadence: Cadence
    period_label: str
    title: str
    data_date: str
    schedule_version: int
    status: str
    created_by: str
    updated_at: str


class ReportOut(ReportSummaryOut):
    blocks: list[ReportBlock]
    style: StyleMemory


class ReportListOut(BaseModel):
    items: list[ReportSummaryOut]
