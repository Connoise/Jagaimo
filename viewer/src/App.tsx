import { NetWorthChart } from "./components/NetWorthChart";

export default function App() {
  return (
    <main
      style={{
        fontFamily: "system-ui, sans-serif",
        background: "#0d1117",
        color: "#c9d1d9",
        minHeight: "100vh",
        margin: 0,
        padding: "1.5rem",
        boxSizing: "border-box",
      }}
    >
      <h1 style={{ marginTop: 0 }}>🥔 Jagaimo</h1>
      <NetWorthChart />
    </main>
  );
}
