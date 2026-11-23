import { render, screen } from '@testing-library/react';
import { afterEach, expect, test } from 'vitest';
import { useAgentView } from '../os/agentView';
import WorkflowRibbon from '../os/WorkflowRibbon';
import { toolLabel as chatToolLabel } from '../programs/chat/labels';
import { toolLabel as workflowToolLabel } from '../programs/workflow/labels';
import { TOOL_LABELS, toolLabel } from './toolLabels';

// 백엔드 도구 등록부(app/tools registry.list_tools)의 이름 37개. 도구를 더하면 여기와 표에 함께 적는다.
const BACKEND_TOOLS = [
  'ask.fill_answers', 'ask.questionnaire', 'calc.cpm', 'conditions.list', 'delay.analyze', 'delay.record',
  'evidence.attach', 'evidence.search', 'field.list', 'files.read', 'files.search', 'files.set_axes',
  'generate.extract_conditions', 'generate.run', 'harness.check', 'info.call', 'info.list', 'info.weather',
  'out.submit_change', 'progress.read', 'report.generate', 'report.learn_template', 'report.list_templates',
  'report.revise', 'rules.propose', 'scenario.create', 'scenario.submit', 'schedule.activity_detail',
  'schedule.create_project', 'schedule.find', 'schedule.import', 'schedule.list', 'schedule.read',
  'schedule.record_actual', 'shorten.make', 'ui.open_window', 'visual.make',
];

afterEach(() => useAgentView.getState().reset());

test('every backend tool has a Korean name in the one shared table (U5)', () => {
  expect(BACKEND_TOOLS).toHaveLength(37);
  expect(BACKEND_TOOLS.filter((t) => !TOOL_LABELS[t])).toEqual([]);
  for (const t of BACKEND_TOOLS) expect(toolLabel(t), t).toMatch(/[가-힣]/);
  expect(toolLabel('모르는.도구')).toBe('모르는.도구');
});

test('chat chips, the workflow window and the ribbon show the same name for a tool (U5)', () => {
  for (const t of BACKEND_TOOLS) {
    expect(chatToolLabel(t), t).toBe(toolLabel(t));
    expect(workflowToolLabel(t), t).toBe(toolLabel(t));
  }
  useAgentView.getState().onToolStart({ run_id: 1, n: 1, tool: 'info.list' });
  expect(useAgentView.getState().ribbon.steps[0].label).toBe(toolLabel('info.list'));
});

test('a ribbon node shows the Korean name and keeps the tool id as its title (U5)', () => {
  useAgentView.getState().onToolStart({ run_id: 1, n: 1, tool: 'field.list' });
  render(<WorkflowRibbon />);
  expect(screen.getByText('1. 현장 데이터 조회').closest('[title]')).toHaveAttribute('title', 'field.list');
});
