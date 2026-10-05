// 세 화면이 공유하는 최소 유틸. sessionStorage 로 스캔 결과를 넘긴다.

function saveScan(result) {
  sessionStorage.setItem("scanResult", JSON.stringify(result));
}

function loadScan() {
  const raw = sessionStorage.getItem("scanResult");
  return raw ? JSON.parse(raw) : null;
}

async function showEngineBadge(elId) {
  try {
    const r = await fetch("../api/engine-mode");
    const d = await r.json();
    document.getElementById(elId).textContent = d.mode === "real" ? "엔진 · 실제" : "엔진 · 목";
  } catch (e) {
    document.getElementById(elId).textContent = "엔진 · 확인 불가";
  }
}

const VERDICT_LABEL = {
  specified: "특정됨",
  narrowed: "좁혀짐",
  weak_signal: "약한 신호",
  abstain: "판단 보류",
};

const GRAIN_LABEL = {
  sido: "시도", sigungu: "시군구", eupmyeondong: "읍면동",
  exact: "정확", range: "범위", decade: "연령대",
};

const ATTR_LABEL = {
  age: "나이", sex: "성별", location: "거주지", occupation: "직업",
  family: "가족", commute: "통근", income: "소득",
};
