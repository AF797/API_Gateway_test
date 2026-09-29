"""시연용 샘플 텍스트. 시뮬레이터가 요청에 쓰고, 가상 번역 플랫폼이 번역 결과로 쓴다."""

NOTICE = """[전사 공지] 2026년 하반기 보안 점검 일정 안내
임직원 여러분께 알려드립니다. 정보보안팀은 10월 12일(월)부터 10월 23일(금)까지 2주간 전사 보안 점검을 실시합니다. 점검 기간 동안 각 부서는 업무용 PC의 백신 업데이트 상태와 운영체제 보안 패치 적용 여부를 확인해 주시기 바랍니다. 또한 외부 API 키, 비밀번호 등 인증 정보를 메신저나 이메일로 공유하는 행위는 금지되며, 발견될 경우 즉시 폐기 후 재발급 조치됩니다. 외부 플랫폼 이용이 필요한 경우 반드시 사내 통합 API 게이트웨이를 통해 발급받은 개인 키를 사용해 주십시오. 점검 결과는 11월 첫째 주에 부서별로 공유될 예정이며, 미흡 항목이 있는 부서는 2주 이내에 개선 계획을 제출해야 합니다. 문의 사항은 정보보안팀(내선 2231)으로 연락 주시기 바랍니다. 여러분의 적극적인 협조에 감사드립니다."""

NOTICE_EN = """[Company Notice] Schedule for the H2 2026 Security Inspection
We would like to inform all employees that the Information Security Team will conduct a company-wide security inspection for two weeks, from Monday, October 12 to Friday, October 23. During the inspection period, each department should check whether antivirus software on work PCs is up to date and whether operating system security patches have been applied. Sharing authentication information such as external API keys or passwords via messenger or email is prohibited; if discovered, the credentials will be revoked and reissued immediately. When you need to use an external platform, please be sure to use the personal key issued through the company's unified API gateway. Inspection results will be shared with each department in the first week of November, and departments with deficiencies must submit an improvement plan within two weeks. For inquiries, please contact the Information Security Team (ext. 2231). Thank you for your cooperation."""

# (한국어, 영어, 일본어)
SHORT_TEXTS = [
    ("다음 주 화요일 오후 2시에 공급 계약 관련 회의를 진행하고자 합니다.",
     "We would like to hold a meeting regarding the supply contract next Tuesday at 2 p.m.",
     "来週火曜日の午後2時に、供給契約に関する会議を行いたいと思います。"),
    ("요청하신 견적서를 첨부하오니 검토 부탁드립니다.",
     "Please find attached the quotation you requested for your review.",
     "ご依頼の見積書を添付いたしますので、ご確認をお願いいたします。"),
    ("배송 일정이 3일 정도 지연될 예정입니다. 양해 부탁드립니다.",
     "The delivery schedule is expected to be delayed by about three days. We appreciate your understanding.",
     "配送日程が3日ほど遅れる見込みです。ご了承ください。"),
    ("계약서 초안의 제5조 지급 조건을 수정해 주시기 바랍니다.",
     "Please revise the payment terms in Article 5 of the draft contract.",
     "契約書草案の第5条の支払条件を修正してください。"),
    ("샘플 제품은 이번 주 금요일까지 발송하겠습니다.",
     "We will ship the sample products by this Friday.",
     "サンプル製品は今週金曜日までに発送いたします。"),
]

TRANSLATIONS = {
    "EN": {NOTICE: NOTICE_EN, **{ko: en for ko, en, _ in SHORT_TEXTS}},
    "JA": {ko: ja for ko, _, ja in SHORT_TEXTS},
}

REPORTS = [
    """2026년 3분기 영업 실적 보고
3분기 전사 매출은 842억 원으로 전년 동기 대비 12.4% 증가했습니다. 해외 매출 비중은 38%로 2분기보다 4%p 확대되었으며, 특히 동남아시아 지역 신규 거래처 확보가 성장을 이끌었습니다. 반면 원자재 가격 상승으로 매출원가율이 1.8%p 높아져 영업이익률은 7.1%에 그쳤습니다. 제품군별로는 산업용 센서가 전체 매출의 45%를 차지하며 가장 높은 성장률(21%)을 기록했고, 기존 주력이던 제어 모듈은 교체 수요 감소로 3% 역성장했습니다. 영업 채널 측면에서는 온라인 견적 시스템을 통한 신규 문의가 전 분기 대비 2배 늘었으나 실제 계약 전환율은 18%로 목표치(25%)에 미달했습니다. 4분기에는 전환율 개선을 위해 견적 후 48시간 이내 담당자 후속 연락을 의무화하고, 원가 절감을 위해 주요 원자재 공급처를 2곳 추가 확보할 계획입니다. 연간 목표 매출 3,300억 원 달성을 위해서는 4분기에 약 920억 원의 매출이 필요합니다.""",
    """신규 거래처 검토 의견서
검토 대상은 베트남 호찌민 소재 부품 유통업체로, 연 매출 약 1,200만 달러 규모이며 설립 9년 차입니다. 최근 3년간 매출은 연평균 15% 성장했고 부채비율은 110% 수준으로 업계 평균과 비슷합니다. 현지 주요 전자 제조사 4곳에 납품 실적이 있으며, 당사 산업용 센서의 현지 유통을 희망하고 있습니다. 다만 대금 결제 조건으로 선적 후 90일 지급을 요청하고 있어 당사 기준(60일)보다 길고, 과거 한 차례 결제 지연 이력이 확인되었습니다. 신용보험 가입 시 보험료는 거래액의 0.8% 수준으로 추정됩니다. 검토 결과, 초기 6개월은 거래 한도를 50만 달러로 제한하고 60일 결제 조건과 신용보험 가입을 전제로 거래를 개시하는 것이 적절하다고 판단합니다. 6개월 후 결제 이력을 평가하여 한도 상향과 결제 조건 완화를 재검토하겠습니다.""",
    """9월 고객 불만 처리 결과 보고
9월 접수된 고객 불만은 총 137건으로 전월 대비 9% 감소했습니다. 유형별로는 배송 지연이 52건(38%)으로 가장 많았고, 제품 초기 불량 31건, 설치 문의 27건, 청구 오류 15건, 기타 12건 순이었습니다. 평균 처리 시간은 2.3일로 목표(3일)를 달성했으나, 배송 지연 건은 물류 협력사와의 확인 절차 때문에 평균 4.1일이 소요되었습니다. 초기 불량은 특정 생산 라인의 납땜 공정 문제로 확인되어 9월 18일 설비 점검 후 발생률이 절반으로 줄었습니다. 고객 만족도 조사 결과는 5점 만점에 4.2점으로 전월과 동일합니다. 10월에는 배송 추적 정보를 고객에게 자동 알림으로 제공하여 배송 문의를 줄이고, 청구 오류 방지를 위해 전자세금계산서 발행 전 이중 검증 절차를 도입할 예정입니다.""",
]

CURRENCIES = ["USD", "JPY", "EUR", "CNY", "GBP"]
