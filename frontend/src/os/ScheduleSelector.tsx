import { useCallback, useEffect, useState } from 'react';
import { api } from '../shared/api';
import { useCurrentSchedule } from './currentSchedule';
import MenuGroup from './MenuGroup';

interface ScheduleItem {
  id: number;
  name: string;
  level?: string;
}

const itemText = (s: ScheduleItem) => (s.level ? `${s.name} · ${s.level}` : s.name);

/** 메뉴바 현장 선택. GET /api/schedules 를 펼칠 때마다 다시 읽는다. */
export default function ScheduleSelector() {
  const current = useCurrentSchedule((s) => s.current);
  const setCurrent = useCurrentSchedule((s) => s.setCurrent);
  const [items, setItems] = useState<ScheduleItem[] | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    api<ScheduleItem[]>('/api/schedules')
      .then((list) => {
        setItems(list);
        setFailed(false);
        const cur = useCurrentSchedule.getState().current;
        if (cur && !list.some((s) => s.id === cur.id)) useCurrentSchedule.getState().setCurrent(null);
      })
      .catch(() => setFailed(true));
  }, []);

  useEffect(load, [load]);

  const known = current ? items?.find((s) => s.id === current.id) : undefined;
  const label = current ? (known ? itemText(known) : current.name) : items?.length === 0 ? '일정 없음' : '일정 고르기';

  const note = failed ? '일정 목록을 불러오지 못했습니다.' : items?.length === 0 ? '일정 없음' : undefined;
  return (
    <MenuGroup
      menus={[
        {
          key: 'site',
          label,
          className: 'os-mb-site',
          onOpen: load,
          note,
          items: (items ?? []).map((s) => ({
            label: itemText(s),
            current: s.id === current?.id,
            run: () => setCurrent({ id: s.id, name: s.name }),
          })),
        },
      ]}
    />
  );
}
