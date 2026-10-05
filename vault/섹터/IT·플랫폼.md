---
tags: [nps-2026q3, 섹터]
---
# IT·플랫폼

[[국민연금 지분확대 분석 2026-10|분석 허브]]로 돌아가기

## 종목
- [[NHN]] — 총점 12, 국민연금 10.12%, 3개월 +60.7%

## Dataview 표
```dataview
TABLE score_total AS "총점", nps_stake AS "국민연금%", fwd_per AS "추정PER", pbr AS "PBR", return_3m AS "3개월%"
FROM #nps-2026q3 AND -#섹터
WHERE sector = "IT·플랫폼"
SORT score_total DESC
```
