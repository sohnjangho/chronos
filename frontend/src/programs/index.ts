import { register } from '../os/registry';
import approvals from './approvals';
import chat from './chat';
import conditions from './conditions';
import explorer from './explorer';
import questionnaire from './questionnaire';
import schedule from './schedule';
import settings from './settings';
import workflow from './workflow';

/** 계획 1 프로그램을 Dock 차례(시스템 → 업무)로 등록한다. */
export function registerPrograms(): void {
  [chat, questionnaire, workflow, approvals, explorer, settings, schedule, conditions].forEach(register);
}
