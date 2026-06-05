import { useState } from "react";
import { PortfolioView } from "./components/PortfolioView";
import { InstrumentView } from "./components/InstrumentView";
import { GroupView } from "./components/GroupView";
import { AnalysisView } from "./components/AnalysisView";
import { TargetsView } from "./components/TargetsView";
import { StatusBar } from "./components/StatusBar";
import { ConnectionBanner } from "./components/ConnectionBanner";

type Tab = "portfolio" | "instruments" | "groups" | "analysis" | "targets";

const TABS: { id: Tab; label: string }[] = [
  { id: "portfolio", label: "Portfolio" },
  { id: "instruments", label: "Instruments" },
  { id: "groups", label: "Groups" },
  { id: "analysis", label: "Analysis" },
  { id: "targets", label: "Targets" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("portfolio");
  return (
    <div className="app">
      <header className="topbar">
        <h1 className="brand">🥔 Jagaimo</h1>
        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? "tab active" : "tab"}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <StatusBar />
      </header>
      <ConnectionBanner />
      <main className="content">
        {tab === "portfolio" && <PortfolioView />}
        {tab === "instruments" && <InstrumentView />}
        {tab === "groups" && <GroupView />}
        {tab === "analysis" && <AnalysisView />}
        {tab === "targets" && <TargetsView />}
      </main>
    </div>
  );
}
