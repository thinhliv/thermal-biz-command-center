import React, { useState, useEffect } from 'react';
import { 
  Flame, 
  Snowflake, 
  TrendingUp, 
  DollarSign, 
  Zap, 
  AlertTriangle, 
  CheckCircle2, 
  Maximize2, 
  Smartphone, 
  Monitor, 
  Clock, 
  Activity,
  Layers,
  ChevronRight,
  ShieldAlert
} from 'lucide-react';

interface Equipment {
  code: string;
  name: string;
  temp: number;
  pressure: number;
  power: number;
  cop: number;
  status: 'RUNNING' | 'WARNING' | 'ALARM';
  type: 'cold' | 'heat' | 'chiller';
}

const INITIAL_EQUIPMENTS: Equipment[] = [
  { code: 'KHO_DONG_01', name: 'Kho Đông Sâu Hải Sản (-25°C)', temp: -23.8, pressure: 1.85, power: 42.5, cop: 3.85, status: 'RUNNING', type: 'cold' },
  { code: 'KHO_MAT_02', name: 'Kho Mát Nông Sản & Trái Cây (+2°C)', temp: 3.2, pressure: 3.40, power: 16.2, cop: 4.20, status: 'RUNNING', type: 'cold' },
  { code: 'CHILLER_01', name: 'Trạm Chiller Trung Tâm Tòa Nhà', temp: 6.8, pressure: 4.10, power: 68.0, cop: 4.60, status: 'RUNNING', type: 'chiller' },
  { code: 'LO_HOI_01', name: 'Lò Hơi Công Nghiệp Đốt Tầng Sôi', temp: 178.5, pressure: 9.20, power: 110.0, cop: 0.89, status: 'RUNNING', type: 'heat' },
  { code: 'CAP_DONG_03', name: 'Hầm Cấp Đông Gió Nhanh 03', temp: -32.1, pressure: 1.45, power: 88.0, cop: 3.20, status: 'WARNING', type: 'cold' },
];

export default function App() {
  const [equipments, setEquipments] = useState<Equipment[]>(INITIAL_EQUIPMENTS);
  const [currentTime, setCurrentTime] = useState(new Date());
  const [isMobileMode, setIsMobileMode] = useState(false);
  const [isKiosk, setIsKiosk] = useState(false);

  // Financial state (VND)
  const todayRevenue = 145200000;
  const mtdRevenue = 3480000000;
  const targetRevenue = 4000000000;
  const electricityCost = 38500000;
  const grossMargin = Math.round(((todayRevenue - electricityCost) / todayRevenue) * 100);

  // Receivables
  const totalDebt = 317000000;
  const overdueDebt = 242000000;

  // Real-time clock and micro-fluctuation simulation
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date());
      // Small realistic thermal jitter
      setEquipments(prev => prev.map(eq => {
        const delta = (Math.random() - 0.5) * 0.2;
        return {
          ...eq,
          temp: Number((eq.temp + delta).toFixed(1)),
          power: Number((eq.power + (Math.random() - 0.5)).toFixed(1))
        };
      }));
    }, 3000);
    return () => clearInterval(timer);
  }, []);

  const formatVND = (num: number) => {
    return new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND', maximumFractionDigits: 0 }).format(num);
  };

  const toggleFullScreen = () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen();
      setIsKiosk(true);
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen();
        setIsKiosk(false);
      }
    }
  };

  return (
    <div className={`min-h-screen bg-[#0b0f19] text-slate-100 flex flex-col ${isMobileMode ? 'max-w-md mx-auto border-x border-slate-800 shadow-2xl' : 'w-full'}`}>
      
      {/* 1. TOP HEADER / CONTROL BAR */}
      <header className="bg-[#111827] border-b border-slate-800 px-4 py-3 flex flex-wrap items-center justify-between gap-3 sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <div className="bg-cyan-500/10 text-cyan-400 p-2 rounded-lg border border-cyan-500/20">
            <Flame className="w-6 h-6 text-amber-500 animate-pulse" />
          </div>
          <div>
            <h1 className="font-bold text-base md:text-lg tracking-wide flex items-center gap-2">
              EXECUTIVE COMMAND CENTER
              <span className="text-xs font-normal px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
                Nhiệt &times; Kinh Doanh
              </span>
            </h1>
            <p className="text-xs text-slate-400">Hệ thống Điều hành Tổng thể Ban Giám Đốc</p>
          </div>
        </div>

        {/* Status indicators & View toggles */}
        <div className="flex items-center gap-2 md:gap-4 text-xs">
          <div className="hidden sm:flex items-center gap-1.5 bg-slate-900 px-3 py-1.5 rounded-full border border-slate-800">
            <Clock className="w-3.5 h-3.5 text-slate-400" />
            <span className="font-mono text-slate-200">
              {currentTime.toLocaleTimeString('vi-VN')}
            </span>
          </div>

          <div className="flex items-center gap-1 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 px-2.5 py-1 rounded-full">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping" />
            <span className="font-medium">Live Synced</span>
          </div>

          {/* Switcher: Mobile simulation vs PC Kiosk */}
          <button 
            onClick={() => setIsMobileMode(!isMobileMode)}
            title="Chuyển đổi giao diện Mobile / PC"
            className="flex items-center gap-1 bg-slate-800 hover:bg-slate-700 text-slate-200 px-2.5 py-1.5 rounded-lg border border-slate-700 transition"
          >
            {isMobileMode ? <Monitor className="w-3.5 h-3.5" /> : <Smartphone className="w-3.5 h-3.5" />}
            <span className="hidden sm:inline">{isMobileMode ? 'Xem dạng PC' : 'Xem dạng Mobile'}</span>
          </button>

          <button 
            onClick={toggleFullScreen}
            title="Chế độ TV Kiosk Toàn màn hình"
            className="p-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg border border-slate-700 transition"
          >
            <Maximize2 className="w-4 h-4" />
          </button>
        </div>
      </header>

      {/* 2. ALERT TICKER BAR */}
      <div className="bg-amber-950/40 border-b border-amber-800/40 px-4 py-2 flex items-center gap-2 text-xs text-amber-200">
        <ShieldAlert className="w-4 h-4 text-amber-400 shrink-0" />
        <div className="overflow-hidden whitespace-nowrap">
          <span className="font-semibold text-amber-300 mr-2">[CẢNH BÁO KHẨN CẤP]:</span>
          <span>Hầm Cấp Đông 03 tiệm cận -32.1°C | Khách hàng An Phát quá hạn 48 ngày (115tr) | Tự động chuyển đổi công suất điện Giờ Thấp Điểm (Tiết kiệm 35%).</span>
        </div>
      </div>

      {/* 3. MAIN DASHBOARD CONTENT */}
      <main className="p-4 md:p-6 flex-1 space-y-6">
        
        {/* TOP ROW: EXECUTIVE HIGH-LEVEL METRICS */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
          
          {/* Card 1: Doanh số hôm nay */}
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-4 hover:border-cyan-500/40 transition">
            <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
              <span>DOANH SỐ HÔM NAY</span>
              <DollarSign className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="text-xl sm:text-2xl font-bold font-mono text-emerald-400">
              {formatVND(todayRevenue)}
            </div>
            <div className="text-[11px] text-emerald-400/80 flex items-center gap-1 mt-1">
              <TrendingUp className="w-3 h-3" /> +12.4% so với hôm qua
            </div>
          </div>

          {/* Card 2: Chi phí điện & Biên lợi nhuận */}
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-4 hover:border-amber-500/40 transition">
            <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
              <span>CHI PHÍ ĐIỆN VẬN HÀNH</span>
              <Zap className="w-4 h-4 text-amber-400" />
            </div>
            <div className="text-xl sm:text-2xl font-bold font-mono text-amber-400">
              {formatVND(electricityCost)}
            </div>
            <div className="text-[11px] text-slate-300 flex items-center justify-between mt-1">
              <span>Biên lợi nhuận gộp:</span>
              <span className="font-bold text-cyan-400 font-mono">{grossMargin}%</span>
            </div>
          </div>

          {/* Card 3: Công nợ quá hạn */}
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-4 hover:border-rose-500/40 transition">
            <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
              <span>NỢ QUÁ HẠN BÁO ĐỘNG</span>
              <AlertTriangle className="w-4 h-4 text-rose-400" />
            </div>
            <div className="text-xl sm:text-2xl font-bold font-mono text-rose-400">
              {formatVND(overdueDebt)}
            </div>
            <div className="text-[11px] text-slate-400 mt-1">
              Tổng nợ: <span className="text-slate-200 font-mono">{formatVND(totalDebt)}</span>
            </div>
          </div>

          {/* Card 4: Hiệu suất Kỹ thuật Nhiệt (COP) */}
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-4 hover:border-cyan-500/40 transition">
            <div className="flex items-center justify-between text-slate-400 text-xs mb-1">
              <span>HIỆU SUẤT LẠNH (COP)</span>
              <Snowflake className="w-4 h-4 text-cyan-400" />
            </div>
            <div className="text-xl sm:text-2xl font-bold font-mono text-cyan-400 flex items-baseline gap-2">
              4.15 <span className="text-xs font-normal text-slate-400">/ 5.0 max</span>
            </div>
            <div className="text-[11px] text-emerald-400 flex items-center gap-1 mt-1">
              <CheckCircle2 className="w-3 h-3" /> Vận hành trong dải tối ưu
            </div>
          </div>

        </div>

        {/* MIDDLE SECTION: 3 CORE PILLARS */}
        <div className={`grid ${isMobileMode ? 'grid-cols-1' : 'grid-cols-1 lg:grid-cols-3'} gap-6`}>
          
          {/* PILLAR 1: KỸ THUẬT NHIỆT & GIÁM SÁT MÁY MÓC */}
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 flex flex-col">
            <div className="flex items-center justify-between mb-4 border-b border-slate-800 pb-3">
              <h2 className="font-semibold text-sm flex items-center gap-2 text-cyan-400">
                <Snowflake className="w-4 h-4" />
                GIÁM SÁT KỸ THUẬT NHIỆT
              </h2>
              <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-400">5 Thiết Bị</span>
            </div>

            <div className="space-y-3 flex-1">
              {equipments.map((eq) => (
                <div 
                  key={eq.code} 
                  className={`p-3 rounded-lg border transition ${
                    eq.status === 'WARNING' 
                      ? 'bg-amber-950/20 border-amber-500/40' 
                      : 'bg-slate-900/60 border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium text-slate-200 truncate pr-2">{eq.name}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono font-semibold ${
                      eq.status === 'WARNING' ? 'bg-amber-500/20 text-amber-300' : 'bg-emerald-500/20 text-emerald-300'
                    }`}>
                      {eq.status}
                    </span>
                  </div>
                  <div className="grid grid-cols-4 gap-2 text-center text-xs">
                    <div className="bg-slate-950/50 p-1.5 rounded">
                      <div className="text-[10px] text-slate-400">Nhiệt độ</div>
                      <div className={`font-mono font-bold ${eq.temp < 0 ? 'text-cyan-400' : 'text-amber-400'}`}>
                        {eq.temp}°C
                      </div>
                    </div>
                    <div className="bg-slate-950/50 p-1.5 rounded">
                      <div className="text-[10px] text-slate-400">Áp suất</div>
                      <div className="font-mono font-bold text-slate-200">{eq.pressure} Bar</div>
                    </div>
                    <div className="bg-slate-950/50 p-1.5 rounded">
                      <div className="text-[10px] text-slate-400">Công suất</div>
                      <div className="font-mono font-bold text-amber-400">{eq.power} kW</div>
                    </div>
                    <div className="bg-slate-950/50 p-1.5 rounded">
                      <div className="text-[10px] text-slate-400">Hệ số COP</div>
                      <div className="font-mono font-bold text-emerald-400">{eq.cop}</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* PILLAR 2: TÀI CHÍNH & TIẾN ĐỘ DOANH SỐ */}
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 flex flex-col">
            <div className="flex items-center justify-between mb-4 border-b border-slate-800 pb-3">
              <h2 className="font-semibold text-sm flex items-center gap-2 text-emerald-400">
                <DollarSign className="w-4 h-4" />
                DOANH SỐ & DÒNG TIỀN
              </h2>
              <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-400">Tháng 11/2026</span>
            </div>

            {/* Target Progress Bar */}
            <div className="bg-slate-900/60 p-4 rounded-lg border border-slate-800 mb-4">
              <div className="flex justify-between text-xs mb-1.5">
                <span className="text-slate-400">Tiến độ Chỉ tiêu Tháng</span>
                <span className="font-mono font-bold text-cyan-400">87.0%</span>
              </div>
              <div className="w-full bg-slate-800 h-2.5 rounded-full overflow-hidden">
                <div className="bg-gradient-to-r from-cyan-500 to-emerald-400 h-full w-[87%] rounded-full" />
              </div>
              <div className="flex justify-between text-[11px] text-slate-400 mt-2">
                <span>Đạt: <strong className="text-slate-200">{formatVND(mtdRevenue)}</strong></span>
                <span>Mục tiêu: <strong className="text-slate-200">{formatVND(targetRevenue)}</strong></span>
              </div>
            </div>

            {/* Recent Orders List */}
            <h3 className="text-xs font-semibold text-slate-400 mb-2 uppercase tracking-wider">Đơn hàng dịch vụ mới nhất</h3>
            <div className="space-y-2.5 flex-1">
              {[
                { name: 'Thủy sản Biển Đông', service: 'Cấp đông nhanh hải sản', amount: 125000000, margin: '75%' },
                { name: 'Nông nghiệp Hoàng Gia', service: 'Thuê kho mát hoa quả', amount: 85000000, margin: '79%' },
                { name: 'Chuỗi Lạnh MegaCold', service: 'Bảo quản kem cao cấp', amount: 54000000, margin: '76%' },
                { name: 'Dệt May Tân Bình', service: 'Cung cấp hơi công nghiệp', amount: 72000000, margin: '60%' },
              ].map((ord, idx) => (
                <div key={idx} className="flex items-center justify-between p-2.5 rounded-lg bg-slate-900/40 border border-slate-800/80 text-xs">
                  <div>
                    <div className="font-medium text-slate-200">{ord.name}</div>
                    <div className="text-[11px] text-slate-400">{ord.service}</div>
                  </div>
                  <div className="text-right">
                    <div className="font-mono font-semibold text-emerald-400">{formatVND(ord.amount)}</div>
                    <div className="text-[10px] text-slate-400">Biên LN: <span className="text-cyan-400 font-mono">{ord.margin}</span></div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* PILLAR 3: PHÂN LOẠI CÔNG NỢ & NỢ QUÁ HẠN */}
          <div className="bg-[#111827] border border-slate-800 rounded-xl p-5 flex flex-col">
            <div className="flex items-center justify-between mb-4 border-b border-slate-800 pb-3">
              <h2 className="font-semibold text-sm flex items-center gap-2 text-rose-400">
                <AlertTriangle className="w-4 h-4" />
                SỨC KHỎE CÔNG NỢ (AGING)
              </h2>
              <span className="text-xs px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 font-mono">
                {formatVND(totalDebt)}
              </span>
            </div>

            {/* Aging Bracket Breakdown */}
            <div className="space-y-2 mb-4">
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">Trong hạn (An toàn):</span>
                <span className="font-mono font-bold text-emerald-400">{formatVND(75000000)} (24%)</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">Quá hạn 1-30 ngày:</span>
                <span className="font-mono font-bold text-amber-400">{formatVND(85000000)} (27%)</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">Quá hạn 31-60 ngày:</span>
                <span className="font-mono font-bold text-rose-400">{formatVND(115000000)} (36%)</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">Quá hạn &gt;60 ngày (Báo động):</span>
                <span className="font-mono font-bold text-rose-600">{formatVND(42000000)} (13%)</span>
              </div>
            </div>

            {/* Debt Aging Stacked Bar */}
            <div className="w-full h-3 rounded-full bg-slate-800 flex overflow-hidden mb-5">
              <div style={{ width: '24%' }} className="bg-emerald-500" title="Trong hạn 24%" />
              <div style={{ width: '27%' }} className="bg-amber-500" title="Quá hạn 1-30 ngày 27%" />
              <div style={{ width: '36%' }} className="bg-rose-500" title="Quá hạn 31-60 ngày 36%" />
              <div style={{ width: '13%' }} className="bg-rose-800" title="Quá hạn >60 ngày 13%" />
            </div>

            {/* Top Debtors List */}
            <h3 className="text-xs font-semibold text-slate-400 mb-2 uppercase tracking-wider">Top khách hàng nợ cần xử lý</h3>
            <div className="space-y-2.5 flex-1">
              {[
                { customer: 'Công ty Thực phẩm An Phát', days: 48, amount: 115000000, level: 'CRITICAL' },
                { customer: 'Tập đoàn Nông nghiệp Hoàng Gia', days: 18, amount: 85000000, level: 'WARNING' },
                { customer: 'Hợp tác xã Rau Sạch Đà Lạt', days: 75, amount: 42000000, level: 'DANGER' },
              ].map((debt, idx) => (
                <div key={idx} className="p-2.5 rounded-lg bg-slate-900/40 border border-slate-800 text-xs flex items-center justify-between">
                  <div>
                    <div className="font-medium text-slate-200">{debt.customer}</div>
                    <div className="text-[11px] text-rose-400">Quá hạn {debt.days} ngày</div>
                  </div>
                  <div className="font-mono font-bold text-rose-300">
                    {formatVND(debt.amount)}
                  </div>
                </div>
              ))}
            </div>
          </div>

        </div>

      </main>

      {/* FOOTER STATUS */}
      <footer className="bg-[#111827] border-t border-slate-800 px-4 py-2 text-center text-[11px] text-slate-500">
        Thermal & Business Command Center &bull; Hỗ trợ Windows (.exe), Linux, Android & iOS &bull; Đồng bộ GitHub thinhliv
      </footer>
    </div>
  );
}
