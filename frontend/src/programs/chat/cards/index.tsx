// 카드 등록부. 새 카드 종류는 CARDS 에 한 줄을 더한다: 'card:<kind>'(card 사건) 또는 사건 이름(approval·questionnaire).
// 모르는 종류나 그리다 실패한 카드는 한 줄짜리 중립 카드로 보인다(대화는 계속).
import { Component, type ComponentType, type ReactNode } from 'react';
import Button from '../../../shared/ui/Button';
import ActualCard from './ActualCard';
import { ApprovalCard, AutoAppliedCard } from './ApprovalCards';
import { asNum, asText, Card, OpenQuestionnaire, type CardCtx, type CardProps } from './Card';
import DelayImpactCard from './DelayImpactCard';
import EvidenceCard from './EvidenceCard';
import GenerationCard from './GenerationCard';
import MiniQuestionsCard from './MiniQuestionsCard';
import ResultCard from './ResultCard';
import RuleSavedCard from './RuleSavedCard';
import ScenarioCard from './ScenarioCard';
import ShortenCard from './ShortenCard';
import VisualCard from './VisualCard';

function QuestionnaireCard({ data, ctx }: CardProps) {
  return (
    <Card title="질문지">
      <p>질문지를 열었습니다. 답하지 않은 것은 적어 둔 가정으로 진행합니다.</p>
      <div className="ch-actions">
        <OpenQuestionnaire id={data.id} ctx={ctx} />
        {ctx.failedQuestionnaire !== null && ctx.failedQuestionnaire === asNum(data.id) && (
          <Button variant="primary" onClick={() => ctx.retryResume()}>
            다시 이어 가기
          </Button>
        )}
      </div>
    </Card>
  );
}

function AnswersFilledCard({ data, ctx }: CardProps) {
  return (
    <div className="ch-line-card">
      <span>{`질문지 ${asText(data.questionnaire_id)}에 답 ${asNum(data.count) ?? 0}개를 채웠습니다.`}</span>
      <OpenQuestionnaire id={data.questionnaire_id} ctx={ctx} />
    </div>
  );
}

export const CARDS: Record<string, ComponentType<CardProps>> = {
  'card:generation': GenerationCard,
  'card:generation_result': ResultCard,
  'card:auto_applied': AutoAppliedCard,
  'card:answers_filled': AnswersFilledCard,
  'card:mini_questions': MiniQuestionsCard,
  'card:evidence': EvidenceCard,
  'card:actual_recorded': ActualCard,
  'card:delay_impact': DelayImpactCard,
  'card:shorten_options': ShortenCard,
  'card:scenario_created': ScenarioCard,
  'card:rule_saved': RuleSavedCard,
  'card:visual': VisualCard,
  'card:schedule_file': () => <Card title="공정표 파일">{null}</Card>, // Task 53 서버 사건의 자리 — 그림은 Task 55
  approval: ApprovalCard,
  questionnaire: QuestionnaireCard,
};

const Unknown = ({ kind }: { kind: string }) => <div className="ch-line-card is-muted ch-wrap">{`이 화면에서 보일 수 없는 카드입니다 (${kind})`}</div>;

class CardBoundary extends Component<{ kind: string; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? <Unknown kind={this.props.kind} /> : this.props.children;
  }
}

export function CardView({ event, data, ctx }: { event: string; data: CardProps['data']; ctx: CardCtx }) {
  const key = event === 'card' ? `card:${asText(data.kind)}` : event;
  const View = CARDS[key];
  const kind = event === 'card' ? asText(data.kind) || '알 수 없음' : event;
  if (!View) return <Unknown kind={kind} />;
  return (
    <CardBoundary kind={kind}>
      <View data={data} ctx={ctx} />
    </CardBoundary>
  );
}

export type { CardCtx };
