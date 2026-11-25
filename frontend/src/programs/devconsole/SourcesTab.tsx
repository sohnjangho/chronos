// 프롬프트 · 동적 가이드 · 도메인 지식 원천 열람 탭 (사본 없이 백엔드 원문 파일 직접 표시).
import { useState } from 'react';
import Badge from '../../shared/ui/Badge';
import type { CatalogOut } from './devApi';

type Sources = CatalogOut['sources'];
type Guide = Sources['guides'][number];
type PipelinePrompt = NonNullable<Sources['pipeline_prompts']>[number];

/** 동적 가이드 표와 고른 가이드 원문. */
function GuidesSection({ guides, guide, onPick }: { guides: Guide[]; guide: Guide | undefined; onPick(name: string): void }) {
  return (
    <div className="dc-src-split">
      <table className="dc-cat-table" aria-label="동적 가이드 목록">
        <thead>
          <tr>
            <th>가이드</th>
            <th>원천 파일</th>
            <th>동적 선택 키워드 (select_guides)</th>
            <th>연동 화면</th>
            <th>분량</th>
          </tr>
        </thead>
        <tbody>
          {guides.map((g) => (
            <tr key={g.name} className={`dc-cat-row${guide?.name === g.name ? ' is-picked' : ''}`} onClick={() => onPick(g.name)}>
              <td>
                <button type="button" className="dc-link" onClick={() => onPick(g.name)}>
                  <b>{g.name}</b>
                </button>
              </td>
              <td>
                <code>{g.file}</code>
              </td>
              <td>{g.keywords.length ? g.keywords.map((k) => <span key={k} className="dc-tag">{k}</span>) : <span className="dc-muted">—</span>}</td>
              <td>{g.programs.length ? g.programs.map((p) => <Badge key={p} tone="info">{p}</Badge>) : <span className="dc-muted">공통</span>}</td>
              <td>{`${g.chars.toLocaleString()}자`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {guide && (
        <div className="dc-principles-box">
          <div className="dc-harness-test-head">
            <b>{`${guide.name}.md 원문`}</b>
            <code>{guide.file}</code>
            <Badge tone="info">{`${guide.chars.toLocaleString()}자`}</Badge>
          </div>
          <pre className="dc-code-block">{guide.content}</pre>
        </div>
      )}
    </div>
  );
}

/** 내부 생성 파이프라인 프롬프트 표와 고른 프롬프트 원문. */
function PipelineSection({ pipeline, pipe, onPick }: { pipeline: PipelinePrompt[]; pipe: PipelinePrompt | undefined; onPick(name: string): void }) {
  return (
    <div className="dc-src-split">
      {pipeline.length === 0 ? (
        <p className="dc-empty">표시할 내부 파이프라인 프롬프트가 없습니다.</p>
      ) : (
        <>
          <table className="dc-cat-table" aria-label="내부 파이프라인 프롬프트 목록">
            <thead>
              <tr>
                <th>이름</th>
                <th>원천 파일</th>
                <th>분량</th>
              </tr>
            </thead>
            <tbody>
              {pipeline.map((p) => (
                <tr key={p.name} className={`dc-cat-row${pipe?.name === p.name ? ' is-picked' : ''}`} onClick={() => onPick(p.name)}>
                  <td>
                    <button type="button" className="dc-link" onClick={() => onPick(p.name)}>
                      <b>{p.name}</b>
                    </button>
                  </td>
                  <td>
                    <code>{p.file}</code>
                  </td>
                  <td>{`${p.chars.toLocaleString()}자`}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {pipe && (
            <div className="dc-principles-box">
              <div className="dc-harness-test-head">
                <b>{`${pipe.name}.md 원문`}</b>
                <code>{pipe.file}</code>
                <Badge tone="info">{`${pipe.chars.toLocaleString()}자`}</Badge>
              </div>
              <pre className="dc-code-block">{pipe.content}</pre>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default function SourcesTab({ catalog }: { catalog: CatalogOut }) {
  const { sources } = catalog;
  const pipeline = sources.pipeline_prompts ?? [];
  const [section, setSection] = useState<'guides' | 'pipeline' | 'system' | 'domains'>('guides');
  const [pickedGuide, setPickedGuide] = useState<string>(sources.guides[0]?.name ?? '');
  const [pickedPipeline, setPickedPipeline] = useState<string>(pipeline[0]?.name ?? '');
  const guide = sources.guides.find((g) => g.name === pickedGuide) ?? sources.guides[0];
  const pipe = pipeline.find((p) => p.name === pickedPipeline) ?? pipeline[0];

  return (
    <div className="dc-scroll dc-cat-wrap">
      <div className="dc-cat-header">
        <h2 className="dc-cat-h2">프롬프트 · 동적 가이드 · 도메인 지식 원천</h2>
        <p className="dc-muted">
          화면용 사본이 아니라 에이전트 컨텍스트 조립기(<code>app/agent/context.py</code>)와 내부 생성 파이프라인이 실제로 읽는 마크다운·YAML 원천 파일을 그대로 보여 줍니다.
        </p>
      </div>
      <div className="dc-chip-bar" role="group" aria-label="원천 구분">
        <button type="button" className={`dc-mode-btn${section === 'guides' ? ' is-on' : ''}`} onClick={() => setSection('guides')}>
          {`동적 가이드 (${sources.guides.length}개)`}
        </button>
        <button type="button" className={`dc-mode-btn${section === 'pipeline' ? ' is-on' : ''}`} onClick={() => setSection('pipeline')}>
          {`내부 파이프라인 프롬프트 (${pipeline.length}개)`}
        </button>
        <button type="button" className={`dc-mode-btn${section === 'system' ? ' is-on' : ''}`} onClick={() => setSection('system')}>
          {`기본 시스템 지시문 (${sources.system_chars.toLocaleString()}자)`}
        </button>
        <button type="button" className={`dc-mode-btn${section === 'domains' ? ' is-on' : ''}`} onClick={() => setSection('domains')}>
          {`도메인 팩 · 정밀도 (${sources.domains.length}개)`}
        </button>
      </div>

      {section === 'guides' && (
        <GuidesSection guides={sources.guides} guide={guide} onPick={setPickedGuide} />
      )}

      {section === 'pipeline' && (
        <PipelineSection pipeline={pipeline} pipe={pipe} onPick={setPickedPipeline} />
      )}

      {section === 'system' && (
        <div className="dc-principles-box">
          <div className="dc-harness-test-head">
            <b>기본 시스템 프롬프트 원문</b>
            <code>{sources.system_file}</code>
            <Badge tone="info">{`${sources.system_chars.toLocaleString()}자`}</Badge>
          </div>
          <pre className="dc-code-block">{sources.system_raw}</pre>
        </div>
      )}

      {section === 'domains' && (
        <div className="dc-src-split">
          {sources.domains.map((d) => (
            <div key={d.id} className="dc-principles-box">
              <div className="dc-harness-test-head">
                <b>{`${d.name} (${d.id})`}</b>
                <code>{d.file}</code>
              </div>
              <pre className="dc-code-block">{d.knowledge}</pre>
            </div>
          ))}
          <div className="dc-principles-box">
            <b>일정 정밀도 정의 (L1 ~ L5)</b>
            <pre className="dc-code-block">{sources.levels_prompt}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
