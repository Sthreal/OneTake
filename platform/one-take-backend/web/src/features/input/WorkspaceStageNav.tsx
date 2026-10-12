import { Icon } from "../../shared/ui/Icon";
import { WORKSPACE_STAGES, getStageState, type WorkspaceStageId } from "./workspaceStages";

interface WorkspaceStageNavProps {
  activeStage: WorkspaceStageId;
  currentStage: WorkspaceStageId;
  onSelect: (stage: WorkspaceStageId) => void;
}

export function WorkspaceStageNav({ activeStage, currentStage, onSelect }: WorkspaceStageNavProps) {
  return (
    <nav className="stage-navigation" aria-label="商品视频生产阶段">
      {WORKSPACE_STAGES.map((stage) => {
        const state = getStageState(stage.id, activeStage, currentStage);
        const disabled = state === "locked";
        return (
          <button
            className={`stage-nav-item is-${state}`}
            type="button"
            key={stage.id}
            disabled={disabled}
            aria-current={state === "active" ? "step" : undefined}
            onClick={() => onSelect(stage.id)}
          >
            <span className="stage-nav-number">
              {state === "done" ? <Icon name="check" size={13} /> : disabled ? <Icon name="lock" size={12} /> : `0${stage.id}`}
            </span>
            <span>
              <strong>{stage.title}</strong>
              <small>{stage.detail}</small>
            </span>
          </button>
        );
      })}
    </nav>
  );
}

