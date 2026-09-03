import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import torch

try:
    from .train import ChangeClassifier, build_feature_matrix
except ImportError:
    from train import ChangeClassifier, build_feature_matrix


DEFAULT_COLUMNS = [
    "homework_id",
    "student_id",
    "file_path",
    "old_position_merged",
    "new_position_merged",
    "label",
]


def merge_child_positions(change_data):
    children = change_data.get("children", []) if isinstance(change_data, dict) else []
    if not children:
        return "N/A", "N/A"

    old_starts = [child.get("old_start", -1) for child in children]
    old_ends = [child.get("old_end", -1) for child in children]
    new_starts = [child.get("start_pos", -1) for child in children]
    new_ends = [child.get("end_pos", -1) for child in children]

    def merge(starts, ends):
        valid_starts = [value for value in starts if value != -1]
        valid_ends = [value for value in ends if value != -1]
        if valid_starts and valid_ends:
            return f"[{min(valid_starts)}, {max(valid_ends)}]"
        if starts and ends and all(value == -1 for value in starts) and all(value == -1 for value in ends):
            return "[-1, -1]"
        return "N/A"

    return merge(old_starts, old_ends), merge(new_starts, new_ends)


def predict_with_checkpoint(test_df, checkpoint_path):
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    type_vocab = checkpoint["type_vocab"]
    token_vocab = checkpoint["token_vocab"]
    threshold = checkpoint["threshold"]

    x_test = build_feature_matrix(test_df, type_vocab, token_vocab)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = ChangeClassifier(input_dim=x_test.shape[1])
    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(device)
    model.eval()

    with torch.no_grad():
        x_test_t = torch.tensor(x_test, dtype=torch.float32).to(device)
        logits = model(x_test_t)
        probs = torch.sigmoid(logits).cpu().numpy()

    preds = (probs >= threshold).astype(int)
    return probs, preds, threshold


def build_output_df(test_df, preds):
    positive_df = test_df.iloc[np.where(preds == 1)[0]].copy()
    old_positions = []
    new_positions = []
    for _, row in positive_df.iterrows():
        old_pos, new_pos = merge_child_positions(row.get("change_data", {}))
        old_positions.append(old_pos)
        new_positions.append(new_pos)

    positive_df["old_position_merged"] = old_positions
    positive_df["new_position_merged"] = new_positions

    for column in DEFAULT_COLUMNS:
        if column not in positive_df.columns:
            positive_df[column] = np.nan

    output_df = positive_df[DEFAULT_COLUMNS].copy()
    output_df.rename(
        columns={
            "homework_id": "课程id",
            "student_id": "学生id",
            "file_path": "文件路径",
            "old_position_merged": "代码变更修改前的位置",
            "new_position_merged": "代码变更修改后的位置",
            "label": "变更实际是否是正样本",
        },
        inplace=True,
    )
    return output_df


def parse_args():
    root = Path(os.environ.get("HIRETEST_DERIVED_DATA_ROOT", Path(__file__).resolve().parents[2] / "data" / "restricted"))
    parser = argparse.ArgumentParser(
        description="Export positive_predictions1-style Excel without training or mutating existing result files."
    )
    parser.add_argument(
        "--test-df",
        default=str(root / "test_df_by_student.pkl"),
        help="Existing test_df_by_student.pkl produced by the original split.",
    )
    parser.add_argument(
        "--model",
        default=str(root / "final_model.pth"),
        help="Existing trained model checkpoint.",
    )
    parser.add_argument(
        "--output",
        default=str(root / "positive_predictions1.xlsx"),
        help="Excel file to create.",
    )
    parser.add_argument(
        "--use-existing-predictions",
        action="store_true",
        help="Use predicted_label already stored in the pkl instead of recomputing with the checkpoint.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing the output Excel if it already exists.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    test_df_path = Path(args.test_df)
    model_path = Path(args.model)
    output_path = Path(args.output)

    if not test_df_path.is_file():
        raise FileNotFoundError(f"Missing test df: {test_df_path}")
    if not args.use_existing_predictions and not model_path.is_file():
        raise FileNotFoundError(f"Missing model checkpoint: {model_path}")
    if output_path.exists() and not args.overwrite:
        raise FileExistsError(f"{output_path} already exists; pass --overwrite to replace it")

    test_df = pd.read_pickle(test_df_path)
    if args.use_existing_predictions:
        if "predicted_label" not in test_df.columns:
            raise ValueError("test df has no predicted_label column; omit --use-existing-predictions")
        preds = test_df["predicted_label"].to_numpy(dtype=int)
        threshold = None
    else:
        _, preds, threshold = predict_with_checkpoint(test_df, model_path)

    output_df = build_output_df(test_df, preds)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_df.to_excel(output_path, index=False, engine="openpyxl")

    print(f"Loaded rows: {len(test_df)}")
    if threshold is not None:
        print(f"Checkpoint threshold: {threshold:.4f}")
    print(f"Positive rows exported: {len(output_df)}")
    print(f"Saved to: {output_path}")


if __name__ == "__main__":
    main()
