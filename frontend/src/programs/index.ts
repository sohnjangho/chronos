import { register } from '../os/registry';
import approvals from './approvals';
import chat from './chat';
import compare from './compare';
import conditions from './conditions';
import contacts from './contacts';
import cpm from './cpm';
import delays from './delays';
import devconsole from './devconsole';
import explorer from './explorer';
import gantt from './gantt';
import library from './library';
import progress from './progress';
import projects from './projects';
import questionnaire from './questionnaire';
import reports from './reports';
import scheduleTable from './schedule-table';
import settings from './settings';
import workflow from './workflow';

/** 프로그램을 Dock 차례(시스템 → 업무)로 등록한다. 일정 도구는 스케줄 · 간트차트 · CPM · 공정률. 프로젝트 관리·연락처는 현장 관리자에게 없다. */
export function registerPrograms(): void {
  [chat, questionnaire, workflow, approvals, explorer, settings, devconsole, scheduleTable, gantt, cpm, progress, compare, conditions, delays, reports, projects, contacts, library].forEach(register);
}
