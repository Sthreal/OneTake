import { InputWorkspace } from "./features/input/InputWorkspace";
import { StudioWorkspace } from "./features/workspace/StudioWorkspace";

export default function App() {
  const useLegacyWorkspace = new URLSearchParams(window.location.search).get("legacy") === "1";
  return useLegacyWorkspace ? <InputWorkspace /> : <StudioWorkspace />;
}
