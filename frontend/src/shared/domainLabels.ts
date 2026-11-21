// 모든 프로그램(대화·탐색기·조건·승인함)에서 공용으로 쓰는 분야 표시 이름.
// 전문 팩(construction·manufacturing) 외 범용 분야 id 도 한국어로 깔끔하게 보여 주고, 모르는 값은 원문을 그대로 쓴다.

const DOMAIN_LABELS: Record<string, string> = {
  construction: '건설',
  manufacturing: '생산',
  production: '생산',
  rnd: 'R&D 연구개발',
  research: '연구개발',
  permitting: '인허가',
  procurement: '자재 공급',
  software: 'SW 개발',
  marketing: '마케팅·행사',
  event: '행사·운영',
  commercialization: '사업화',
  general: '일반',
};

export const domainLabel = (domain: string): string => DOMAIN_LABELS[domain.toLowerCase()] ?? domain;
