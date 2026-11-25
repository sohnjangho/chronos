import { useState, type FormEvent } from 'react';
import Button from '../shared/ui/Button';
import Field from '../shared/ui/Field';
import { useSignIn } from './auth';
import { useSession } from './session';
import SignupModal from './SignupModal';
import { useDetectedDevice, useDeviceMode, type DeviceMode, type ResolvedDevice } from './useIsMobile';

const DETECTED_LABEL: Record<ResolvedDevice, string> = {
  desktop: '데스크톱',
  tablet: '태블릿',
  phone: '스마트폰',
};

const LOGIN_DEVICES: { id: DeviceMode; label: string }[] = [
  { id: 'auto', label: '자동' },
  { id: 'desktop', label: '데스크톱' },
  { id: 'tablet', label: '태블릿' },
  { id: 'phone', label: '스마트폰' },
];

/** 예전 토큰(기기 세션 전)이 401 session_upgraded 로 로그아웃됐을 때의 부드러운 안내. */
function UpgradedNote() {
  const upgraded = useSession((s) => s.signedOutReason === 'session_upgraded');
  return upgraded ? (
    <p className="os-card-note" role="status">
      보안 강화로 한 번 다시 로그인해 주세요
    </p>
  ) : null;
}

/** 접속 화면(자동 · 데스크톱 · 태블릿 · 스마트폰) 고르기. */
function DevicePicker({ detected }: { detected: ResolvedDevice }) {
  const deviceMode = useDeviceMode((s) => s.mode);
  const setDeviceMode = useDeviceMode((s) => s.setMode);
  return (
    <div className="os-login-device">
      <div className="os-login-dev-head">
        <span>접속 화면</span>
        <span className="os-login-dev-detected">{`자동 감지: ${DETECTED_LABEL[detected]}`}</span>
      </div>
      <div className="os-login-dev-seg" role="group" aria-label="접속 화면 선택">
        {LOGIN_DEVICES.map((item) => (
          <button
            key={item.id}
            type="button"
            className="os-login-dev-btn"
            aria-pressed={deviceMode === item.id}
            onClick={() => setDeviceMode(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/** 왼쪽 위 브랜드 로고(움직이는 로고 + 정지 그림)와 한 줄 소개. */
function LoginBrand() {
  return (
    <div className="os-login-brand">
      <div className="os-login-logo-wrap">
        <video
          className="os-login-logo-video"
          autoPlay
          loop
          muted
          playsInline
          preload="auto"
          poster="/media/chronos-logo-poster.jpg"
          aria-label="ChronOS — AI Schedule Agent"
        >
          <source src="/media/chronos-logo-motion.mp4" type="video/mp4" />
        </video>
        <img src="/media/chronos-logo.png" alt="" aria-hidden="true" className="os-login-logo-static" />
      </div>
      <div className="os-login-tagline">일정을 만들고, 지키고, 고치는 에이전트 OS</div>
    </div>
  );
}

/** 시안 「로그인」: 우측 홀로그램 배경 동영상 + 좌측 브랜드 로고·글래스 로그인 패널. */
export default function Login() {
  const [loginId, setLoginId] = useState('');
  const [password, setPassword] = useState('');
  const [signupOpen, setSignupOpen] = useState(false);
  const { busy, error, submit } = useSignIn();
  const detected = useDetectedDevice();

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void submit(loginId, password);
  }

  return (
    <div className="os-login" data-device={detected}>
      <div className="os-login-backdrop" aria-hidden="true" />

      <div className="os-login-pane">
        <LoginBrand />

        <form className="os-card os-login-card" onSubmit={onSubmit}>
          <h1 className="os-card-title">로그인</h1>
          <Field label="아이디">
            <input value={loginId} onChange={(e) => setLoginId(e.target.value)} autoComplete="username" required autoFocus />
          </Field>
          <Field label="비밀번호">
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </Field>
          <DevicePicker detected={detected} />
          {error && (
            <p className="os-card-error" role="alert">
              {error}
            </p>
          )}
          {!error && <UpgradedNote />}
          <Button type="submit" variant="primary" className="os-card-submit" disabled={busy}>
            들어가기
          </Button>
          <div className="os-login-links">
            <Button type="button" className="os-card-signup-btn" onClick={() => setSignupOpen(true)}>
              회원가입
            </Button>
          </div>
          <p className="os-card-note">계정은 회원가입 신청 뒤 관리자가 승인합니다. 등급은 관리자 · 사용자 · 현장 관리자 세 가지입니다.</p>
        </form>

        <div className="os-login-foot">2026 .EXE-THON 출품작 · Liner API로 동작합니다</div>
      </div>

      <SignupModal open={signupOpen} onClose={() => setSignupOpen(false)} />

      <div className="os-login-stage" aria-hidden="true">
        <video
          className="os-login-video"
          autoPlay
          loop
          muted
          playsInline
          preload="auto"
          poster="/media/login-poster.jpg"
          aria-hidden="true"
        >
          <source src="/media/login-bg.mp4" type="video/mp4" />
        </video>
      </div>
    </div>
  );
}
