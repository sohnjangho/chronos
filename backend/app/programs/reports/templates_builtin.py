"""기본 제공 보고서 양식(월간 · 분기별)."""

from app.programs.reports.schemas import (
    Cadence,
    StyleMemory,
    TemplateOut,
    TemplateSection,
)

BUILTIN_MONTHLY = TemplateOut(
    id=None,
    builtin_key="monthly",
    schedule_id=None,
    project_name=None,
    cadence="monthly",
    name="기본 월간 공정 보고서",
    is_default=False,
    is_builtin=True,
    sections=[
        TemplateSection(
            id="s1",
            heading="1. 월간 공정 요약",
            block_kind="prose",
            data_binding="summary_prose",
            section_prompt="이번 달 계획 대비 실적 공정률, SPI, 준공 전망과 핵심 조치를 3~4문장으로 요약",
        ),
        TemplateSection(
            id="s2",
            heading="2. 핵심 공정 지표",
            block_kind="kpi",
            data_binding="kpi_summary",
        ),
        TemplateSection(
            id="s3",
            heading="3. WBS 공종별 공정률 현황",
            block_kind="table",
            data_binding="wbs_table",
            table_columns=["WBS", "가중치", "계획(%)", "실적(%)", "차이(%p)"],
        ),
        TemplateSection(
            id="s4",
            heading="4. 월간 공정률 S-커브",
            block_kind="chart",
            data_binding="s_curve_month",
        ),
        TemplateSection(
            id="s5",
            heading="5. 주요 마일스톤 추적",
            block_kind="table",
            data_binding="milestone_table",
            table_columns=["마일스톤", "Plan", "실적·예측", "차이(일)", "상태"],
        ),
        TemplateSection(
            id="s6",
            heading="6. 지연 현황 및 만회 대책",
            block_kind="table",
            data_binding="delay_table",
            table_columns=["사건", "책임", "준공 영향", "상태·대책"],
        ),
        TemplateSection(
            id="s7",
            heading="7. 익월 중점 추진 일정",
            block_kind="table",
            data_binding="lookahead_3w",
            table_columns=["일자", "구분", "작업명", "선행·유의사항"],
        ),
    ],
    style=StyleMemory(tone="~습니다 (간결한 보고서 체)", date_format="YYYY.MM.DD", number_precision=1),
    created_by="ChronOS",
)

BUILTIN_QUARTERLY = TemplateOut(
    id=None,
    builtin_key="quarterly",
    schedule_id=None,
    project_name=None,
    cadence="quarterly",
    name="기본 분기별 공정 보고서",
    is_default=False,
    is_builtin=True,
    sections=[
        TemplateSection(
            id="s1",
            heading="1. 분기 경영 요약",
            block_kind="prose",
            data_binding="summary_prose",
            section_prompt="분기 전체 진도 성과, SPI 추세, 마일스톤 준공 리스크와 차분기 전략을 핵심 위주로 정리",
        ),
        TemplateSection(
            id="s2",
            heading="2. 분기 핵심 공정 성과 (KPI)",
            block_kind="kpi",
            data_binding="kpi_summary",
        ),
        TemplateSection(
            id="s3",
            heading="3. 분기 SPI 추이 및 공정 흐름",
            block_kind="chart",
            data_binding="spi_trend",
        ),
        TemplateSection(
            id="s4",
            heading="4. WBS 공종별 누적 진도",
            block_kind="table",
            data_binding="wbs_table",
            table_columns=["WBS", "가중치", "계획(%)", "실적(%)", "차이(%p)"],
        ),
        TemplateSection(
            id="s5",
            heading="5. 핵심 마일스톤 달성 및 준공 전망",
            block_kind="table",
            data_binding="milestone_table",
            table_columns=["마일스톤", "Plan", "실적·예측", "차이(일)", "상태"],
        ),
        TemplateSection(
            id="s6",
            heading="6. 분기 주요 지연 요인 및 책임 분석",
            block_kind="table",
            data_binding="delay_table",
            table_columns=["사건", "책임", "준공 영향", "상태·대책"],
        ),
        TemplateSection(
            id="s7",
            heading="7. 만회 시나리오 비교 및 차분기 전략",
            block_kind="table",
            data_binding="scenario_compare",
            table_columns=["시나리오", "예상 준공", "준공 차이", "크리티컬 수", "상태"],
        ),
    ],
    style=StyleMemory(tone="~습니다 (경영 보고서 체)", date_format="YYYY.MM.DD", number_precision=1),
    created_by="ChronOS",
)


def builtin_template(cadence: Cadence) -> TemplateOut:
    return BUILTIN_QUARTERLY.model_copy(deep=True) if cadence == "quarterly" else BUILTIN_MONTHLY.model_copy(deep=True)
