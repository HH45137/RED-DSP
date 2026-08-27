"""RED DSP assembly dependency analyser and VLIW bundle scheduler."""

from __future__ import annotations

import csv
import io
import tempfile
import tkinter as tk
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from .red_dsp_emu import RedDSP
except ImportError:
    from red_dsp_emu import RedDSP

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_ISA_PATH = ROOT_DIR / "isa.csv"
SLOT_ORDER = ("ALU0", "ALU1", "SFU0", "LSU0")
SLOT_COLORS = {
    "ALU0": "#1f6feb",
    "ALU1": "#0969da",
    "SFU0": "#8250df",
    "LSU0": "#1a7f37",
}
DEPENDENCY_COLORS = {
    "RAW": "#cf222e",
    "WAR": "#bf8700",
    "WAW": "#8250df",
}


@dataclass(frozen=True)
class AssemblyInstruction:
    opcode: str
    operands: tuple[str, str, str, str]
    definition: dict[str, str]
    line_number: int
    source: str

    @property
    def instruction_type(self) -> str:
        return self.definition["TYPE"]

    @property
    def action(self) -> str:
        return self.definition["ACTION"].split()[0]

    def label(self) -> str:
        return f"{self.opcode} {' '.join(self.operands)}"


@dataclass(frozen=True)
class DependencyEdge:
    source: int
    target: int
    kind: str
    register: str


@dataclass(frozen=True)
class ScheduleAnalysis:
    instructions: list[AssemblyInstruction]
    bundles: list[dict[str, int | None]]
    edges: list[DependencyEdge]
    assembly: str
    metrics: dict[str, int | float]
    labels: dict[str, int]


@dataclass(frozen=True)
class ExecutionResult:
    registers: tuple[int, ...]
    memory: dict[int, int]
    pc: int
    bundle_log: str


METRIC_LABELS = (
    ("instruction_count", "Instructions", "Scheduled non-NOP instructions"),
    ("bundle_count", "Cycles / Bundles", "One VLIW bundle is issued per cycle"),
    ("ipc", "IPC", "Average useful instructions issued per cycle"),
    ("slot_utilization_pct", "Total slot utilization", "Used slots / all four-slot capacity"),
    ("nop_ratio_pct", "Empty slot ratio", "NOP slots / all four-slot capacity"),
    ("alu_utilization_pct", "ALU utilization", "ALU instructions / ALU0+ALU1 capacity"),
    ("sfu_utilization_pct", "SFU utilization", "SFU instructions / SFU0 capacity"),
    ("lsu_utilization_pct", "LSU utilization", "LSU instructions / LSU0 capacity"),
    ("parallel_cycle_ratio_pct", "Parallel cycle ratio", "Cycles issuing at least two instructions"),
    ("peak_issue_efficiency_pct", "Peak issue efficiency", "IPC / maximum issue width of four"),
    ("dependency_density", "Dependency density", "Data dependency edges per instruction"),
    ("raw_count", "RAW dependencies", "Read-after-write edges"),
    ("war_count", "WAR dependencies", "Write-after-read edges"),
    ("waw_count", "WAW dependencies", "Write-after-write edges"),
)


def load_isa(path: Path | str = DEFAULT_ISA_PATH) -> dict[str, dict[str, str]]:
    with Path(path).open("r", encoding="utf-8", newline="") as source:
        return {row["OP"]: row for row in csv.DictReader(source)}


def is_register(value: str) -> bool:
    return value == "SP" or (
        value.startswith("R") and value[1:].isdigit() and 0 <= int(value[1:]) < 16
    )


def is_integer(value: str) -> bool:
    try:
        int(value, 0)
        return True
    except ValueError:
        return False


def parse_assembly(
    source: str, isa: dict[str, dict[str, str]]
) -> list[AssemblyInstruction]:
    """Parse linear or bundled source and discard comments and explicit NOPs."""
    instructions: list[AssemblyInstruction] = []
    bundle_depth = 0

    for line_number, raw_line in enumerate(source.splitlines(), start=1):
        code = raw_line.split("//", 1)[0].strip()
        if not code:
            continue
        if code.startswith(".") or code.startswith("#"):
            continue
        if code.endswith(":"):
            continue
        if code == "{":
            bundle_depth += 1
            if bundle_depth > 1:
                raise ValueError(f"Line {line_number}: nested bundle is not supported")
            continue
        if code == "}":
            if bundle_depth == 0:
                raise ValueError(f"Line {line_number}: bundle end without bundle start")
            bundle_depth -= 1
            continue

        fields = code.split()
        opcode = fields[0]
        definition = isa.get(opcode)
        if definition is None:
            raise ValueError(f"Line {line_number}: unknown opcode '{opcode}'")
        if opcode == "NOP":
            continue

        operands = fields[1:]
        if definition["TYPE"] == "FAKE" and not operands:
            operands = ["X", "X", "X", "X"]
        if len(operands) != 4:
            raise ValueError(f"Line {line_number}: {opcode} expects 4 operands")
        if opcode in ("BEQ", "BNE") and not is_integer(operands[3]):
            if not is_register(operands[0]) or not is_register(operands[1]) or operands[2] != "X":
                raise ValueError(
                    f"Line {line_number}: {opcode} expects SRC1 SRC2 X LABEL"
                )
        else:
            for operand, requirement in zip(
                operands,
                (
                    definition["DST"],
                    definition["SRC1"],
                    definition["SRC2"],
                    definition["IMM"],
                ),
            ):
                if requirement == "GR" and not is_register(operand):
                    raise ValueError(
                        f"Line {line_number}: {opcode} expects a register, got '{operand}'"
                    )

        instructions.append(
            AssemblyInstruction(
                opcode=opcode,
                operands=tuple(operands),  # type: ignore[arg-type]
                definition=definition,
                line_number=line_number,
                source=code,
            )
        )

    if bundle_depth:
        raise ValueError("Bundle end is missing")
    return instructions


def collect_labels(
    source: str, isa: dict[str, dict[str, str]] | None = None
) -> dict[str, int]:
    """Map assembly labels to the following linear instruction index."""
    isa = isa or load_isa()
    labels: dict[str, int] = {}
    instruction_index = 0
    for raw_line in source.splitlines():
        code = raw_line.split("//", 1)[0].strip()
        if not code or code in ("{", "}"):
            continue
        if code.endswith(":"):
            labels[code[:-1]] = instruction_index
            continue
        if code.startswith("."):
            continue
        if code.split()[0] in isa:
            if code.split()[0] != "NOP":
                instruction_index += 1
    return labels


def register_accesses(instruction: AssemblyInstruction) -> tuple[set[str], set[str]]:
    """Return read and written registers according to the ISA action semantics."""
    dst, src1, src2, _imm = instruction.operands
    action = instruction.action
    reads: set[str] = set()
    writes: set[str] = set()

    if action == "STORE":
        reads.update(register for register in (dst, src1) if is_register(register))
    elif action in ("BEQ", "BNE"):
        branch_sources = (dst, src1) if not is_integer(_imm) else (src1, src2)
        reads.update(register for register in branch_sources if is_register(register))
    elif action == "JMP":
        if is_register(dst):
            reads.add(dst)
    elif action == "CALL":
        if is_register(src1):
            reads.add(src1)
        if is_register(dst):
            writes.add(dst)
    elif action == "NOP":
        pass
    else:
        if is_register(src1):
            reads.add(src1)
        if is_register(src2) and instruction.definition["SRC2"] == "GR":
            reads.add(src2)
        if is_register(dst):
            writes.add(dst)
        if action == "MAC" and is_register(dst):
            reads.add(dst)

    return reads, writes


def is_barrier(instruction: AssemblyInstruction) -> bool:
    return instruction.instruction_type == "LSU" or instruction.action in {
        "BEQ",
        "BNE",
        "JMP",
        "CALL",
    }


def build_dependencies(
    instructions: list[AssemblyInstruction],
) -> tuple[list[set[int]], list[DependencyEdge]]:
    """Construct RAW, WAR and WAW predecessors and typed dependency edges."""
    predecessors = [set() for _ in instructions]
    edges: list[DependencyEdge] = []
    last_writer: dict[str, int] = {}
    active_readers: dict[str, set[int]] = {}

    for index, instruction in enumerate(instructions):
        reads, writes = register_accesses(instruction)
        for register in reads:
            if register in last_writer:
                source = last_writer[register]
                predecessors[index].add(source)
                edges.append(DependencyEdge(source, index, "RAW", register))
            active_readers.setdefault(register, set()).add(index)
        for register in writes:
            if register in last_writer:
                source = last_writer[register]
                predecessors[index].add(source)
                edges.append(DependencyEdge(source, index, "WAW", register))
            for reader in active_readers.get(register, set()):
                if reader == index:
                    continue
                predecessors[index].add(reader)
                edges.append(DependencyEdge(reader, index, "WAR", register))
            active_readers[register] = set()
            last_writer[register] = index

    return predecessors, edges


def empty_slots() -> dict[str, int | None]:
    return {slot: None for slot in SLOT_ORDER}


def available_slot(
    instruction: AssemblyInstruction, slots: dict[str, int | None]
) -> str | None:
    if instruction.instruction_type == "ALU" or instruction.opcode == "RET":
        for slot in ("ALU0", "ALU1"):
            if slots[slot] is None:
                return slot
    elif instruction.instruction_type == "SFU" and slots["SFU0"] is None:
        return "SFU0"
    elif instruction.instruction_type == "LSU" and slots["LSU0"] is None:
        return "LSU0"
    return None


def schedule_region(
    instructions: list[AssemblyInstruction],
    region_indices: list[int],
    predecessors: list[set[int]],
) -> list[dict[str, int | None]]:
    remaining = set(region_indices)
    scheduled: set[int] = set()
    bundles: list[dict[str, int | None]] = []

    while remaining:
        slots = empty_slots()
        completed = scheduled.copy()
        progress = False
        for index in region_indices:
            if index not in remaining:
                continue
            local_preds = predecessors[index] & remaining | predecessors[index] & scheduled
            if not local_preds.issubset(completed):
                continue
            slot = available_slot(instructions[index], slots)
            if slot is None:
                continue
            slots[slot] = index
            scheduled.add(index)
            remaining.remove(index)
            progress = True
        if not progress:
            raise ValueError(
                "Unable to schedule instructions because the dependency graph is cyclic"
            )
        bundles.append(slots)
    return bundles


def schedule_instructions(
    instructions: list[AssemblyInstruction],
    predecessors: list[set[int]],
    boundaries: set[int] | None = None,
) -> list[dict[str, int | None]]:
    """Schedule code while treating memory and control flow as strict barriers."""
    bundles: list[dict[str, int | None]] = []
    region: list[int] = []
    boundaries = boundaries or set()
    for index, instruction in enumerate(instructions):
        if index in boundaries and region:
            bundles.extend(schedule_region(instructions, region, predecessors))
            region = []
        if is_barrier(instruction):
            if region:
                bundles.extend(schedule_region(instructions, region, predecessors))
                region = []
            slots = empty_slots()
            slot = available_slot(instruction, slots)
            if slot is None:
                raise ValueError(
                    f"Line {instruction.line_number}: cannot allocate {instruction.opcode}"
                )
            slots[slot] = index
            bundles.append(slots)
        else:
            region.append(index)
    if region:
        bundles.extend(schedule_region(instructions, region, predecessors))
    return bundles


def format_bundles(
    instructions: list[AssemblyInstruction], bundles: list[dict[str, int | None]],
    labels: dict[str, int] | None = None,
) -> str:
    labels = labels or {}
    instruction_to_bundle = {
        index: bundle_index
        for bundle_index, bundle in enumerate(bundles)
        for index in bundle.values()
        if index is not None
    }
    label_bundles = {
        label: (instruction_to_bundle[index] if index in instruction_to_bundle else len(bundles))
        for label, index in labels.items()
    }
    lines: list[str] = []
    for bundle in bundles:
        lines.append("{")
        for slot in SLOT_ORDER:
            index = bundle[slot]
            if index is None:
                lines.append("    NOP")
                continue
            instruction = instructions[index]
            if instruction.action in ("BEQ", "BNE") and not is_integer(instruction.operands[3]):
                target = instruction.operands[3]
                if target not in label_bundles:
                    raise ValueError(f"Line {instruction.line_number}: unknown label '{target}'")
                offset = label_bundles[target] - instruction_to_bundle[index]
                if not -(1 << 13) <= offset < (1 << 13):
                    raise ValueError(f"Line {instruction.line_number}: branch offset is out of signed 14-bit range")
                encoded = offset & 0x3FFF
                dst = encoded >> 9
                imm = encoded & 0x1FF
                lines.append(f"    {instruction.opcode} {dst} {instruction.operands[0]} {instruction.operands[1]} {imm}")
            else:
                lines.append(f"    {instruction.label()}")
        lines.append("}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def calculate_metrics(
    instructions: list[AssemblyInstruction],
    bundles: list[dict[str, int | None]],
    edges: list[DependencyEdge],
) -> dict[str, int | float]:
    """Calculate static VLIW issue and execution-unit utilization metrics."""
    instruction_count = len(instructions)
    bundle_count = len(bundles)
    total_capacity = bundle_count * len(SLOT_ORDER)
    slot_counts = {
        slot: sum(bundle[slot] is not None for bundle in bundles)
        for slot in SLOT_ORDER
    }
    alu_count = slot_counts["ALU0"] + slot_counts["ALU1"]
    sfu_count = slot_counts["SFU0"]
    lsu_count = slot_counts["LSU0"]
    occupied_counts = [
        sum(index is not None for index in bundle.values()) for bundle in bundles
    ]
    parallel_cycles = sum(count >= 2 for count in occupied_counts)
    full_cycles = sum(count == len(SLOT_ORDER) for count in occupied_counts)
    dependency_counts = {
        kind: sum(edge.kind == kind for edge in edges) for kind in DEPENDENCY_COLORS
    }

    def percentage(numerator: int, denominator: int) -> float:
        return round(numerator * 100.0 / denominator, 2) if denominator else 0.0

    ipc = instruction_count / bundle_count if bundle_count else 0.0
    return {
        "instruction_count": instruction_count,
        "bundle_count": bundle_count,
        "edge_count": len(edges),
        "total_slot_count": total_capacity,
        "used_slot_count": instruction_count,
        "nop_count": total_capacity - instruction_count,
        "ipc": round(ipc, 3),
        "slot_utilization_pct": percentage(instruction_count, total_capacity),
        "nop_ratio_pct": percentage(total_capacity - instruction_count, total_capacity),
        "alu_instruction_count": alu_count,
        "sfu_instruction_count": sfu_count,
        "lsu_instruction_count": lsu_count,
        "alu0_utilization_pct": percentage(slot_counts["ALU0"], bundle_count),
        "alu1_utilization_pct": percentage(slot_counts["ALU1"], bundle_count),
        "alu_utilization_pct": percentage(alu_count, bundle_count * 2),
        "sfu_utilization_pct": percentage(sfu_count, bundle_count),
        "lsu_utilization_pct": percentage(lsu_count, bundle_count),
        "parallel_cycle_count": parallel_cycles,
        "parallel_cycle_ratio_pct": percentage(parallel_cycles, bundle_count),
        "full_cycle_count": full_cycles,
        "full_cycle_ratio_pct": percentage(full_cycles, bundle_count),
        "peak_issue_efficiency_pct": round(ipc * 25.0, 2),
        "dependency_density": round(len(edges) / instruction_count, 3)
        if instruction_count
        else 0.0,
        "raw_count": dependency_counts["RAW"],
        "war_count": dependency_counts["WAR"],
        "waw_count": dependency_counts["WAW"],
    }


def analyze_assembly(
    source: str, isa_path: Path | str = DEFAULT_ISA_PATH
) -> ScheduleAnalysis:
    isa = load_isa(isa_path)
    instructions = parse_assembly(source, isa)
    labels = collect_labels(source, isa)
    predecessors, edges = build_dependencies(instructions)
    bundles = schedule_instructions(instructions, predecessors, set(labels.values()))
    return ScheduleAnalysis(
        instructions=instructions,
        bundles=bundles,
        edges=edges,
        assembly=format_bundles(instructions, bundles, labels),
        metrics=calculate_metrics(instructions, bundles, edges),
        labels=labels,
    )


def optimize_assembly(
    source: str, isa_path: Path | str = DEFAULT_ISA_PATH
) -> tuple[str, dict[str, int | float]]:
    analysis = analyze_assembly(source, isa_path)
    return analysis.assembly, analysis.metrics


def execute_assembly(
    assembly: str, isa_path: Path | str = DEFAULT_ISA_PATH
) -> ExecutionResult:
    """Execute bundled assembly with RedDSP and return its final machine state."""
    if not assembly.strip():
        raise ValueError("Optimized assembly is empty")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".s",
            delete=False,
        ) as temporary_file:
            temporary_file.write(assembly)
            temporary_path = Path(temporary_file.name)

        dsp = RedDSP()
        output = io.StringIO()
        with redirect_stdout(output):
            dsp.run(str(temporary_path), str(Path(isa_path)))
            dsp.execute_program()
        return ExecutionResult(
            registers=tuple(dsp.regs),
            memory=dict(sorted(dsp.memory.items())),
            pc=dsp.pc,
            bundle_log=output.getvalue().rstrip(),
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def format_execution_result(result: ExecutionResult) -> str:
    """Format emulator output for the GUI result panel."""
    lines = ["=== RedDSP execution ==="]
    if result.bundle_log:
        lines.extend(("", "Decoded bundles:", result.bundle_log))
    lines.extend(("", f"Final PC: {result.pc} (0x{result.pc:08X})", "", "Registers:"))
    for row_start in range(0, len(result.registers), 4):
        row = []
        for index in range(row_start, min(row_start + 4, len(result.registers))):
            value = result.registers[index]
            row.append(f"R{index:02} = {value:10d} (0x{value:08X})")
        lines.append("    ".join(row))

    lines.extend(("", "Memory:"))
    if result.memory:
        for address, value in result.memory.items():
            lines.append(f"[0x{address:08X}] = {value:10d} (0x{value:08X})")
    else:
        lines.append("(no memory was written)")
    return "\n".join(lines) + "\n"


class ScheduleCanvas(ttk.Frame):
    NODE_WIDTH = 210
    NODE_HEIGHT = 48
    COLUMN_GAP = 28
    ROW_GAP = 88
    LEFT_MARGIN = 88
    TOP_MARGIN = 56

    def __init__(self, parent: tk.Widget):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, background="#f6f8fa", highlightthickness=0)
        x_scroll = ttk.Scrollbar(self, orient=tk.HORIZONTAL, command=self.canvas.xview)
        y_scroll = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.analysis: ScheduleAnalysis | None = None

    def render(self, analysis: ScheduleAnalysis | None) -> None:
        self.analysis = analysis
        self.canvas.delete("all")
        if analysis is None or not analysis.bundles:
            self.canvas.create_text(
                24,
                24,
                anchor="nw",
                fill="#57606a",
                font=("Segoe UI", 11),
                text="Optimize assembly to show instruction dependencies and slot usage.",
            )
            self.canvas.configure(scrollregion=(0, 0, 640, 240))
            return

        positions = self._node_positions(analysis)
        self._draw_grid(analysis)
        self._draw_edges(analysis, positions)
        self._draw_nodes(analysis, positions)
        self._draw_legend()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _node_positions(
        self, analysis: ScheduleAnalysis
    ) -> dict[int, tuple[int, int, int, int]]:
        positions: dict[int, tuple[int, int, int, int]] = {}
        for cycle, bundle in enumerate(analysis.bundles):
            y = self.TOP_MARGIN + cycle * (self.NODE_HEIGHT + self.ROW_GAP)
            for column, slot in enumerate(SLOT_ORDER):
                index = bundle[slot]
                if index is None:
                    continue
                x = self.LEFT_MARGIN + column * (self.NODE_WIDTH + self.COLUMN_GAP)
                positions[index] = (x, y, x + self.NODE_WIDTH, y + self.NODE_HEIGHT)
        return positions

    def _draw_grid(self, analysis: ScheduleAnalysis) -> None:
        width = self.LEFT_MARGIN + len(SLOT_ORDER) * (
            self.NODE_WIDTH + self.COLUMN_GAP
        )
        height = self.TOP_MARGIN + len(analysis.bundles) * (
            self.NODE_HEIGHT + self.ROW_GAP
        )
        for column, slot in enumerate(SLOT_ORDER):
            x = self.LEFT_MARGIN + column * (self.NODE_WIDTH + self.COLUMN_GAP)
            self.canvas.create_text(
                x + self.NODE_WIDTH / 2,
                18,
                text=slot,
                fill=SLOT_COLORS[slot],
                font=("Segoe UI Semibold", 11),
            )
            self.canvas.create_rectangle(
                x - 8,
                self.TOP_MARGIN - 18,
                x + self.NODE_WIDTH + 8,
                height - 20,
                outline="#d0d7de",
                dash=(3, 3),
            )
        for cycle in range(len(analysis.bundles)):
            y = self.TOP_MARGIN + cycle * (self.NODE_HEIGHT + self.ROW_GAP)
            self.canvas.create_text(
                16,
                y + self.NODE_HEIGHT / 2,
                anchor="w",
                text=f"C{cycle}",
                fill="#57606a",
                font=("Segoe UI Semibold", 10),
            )
            for column, slot in enumerate(SLOT_ORDER):
                x = self.LEFT_MARGIN + column * (self.NODE_WIDTH + self.COLUMN_GAP)
                if analysis.bundles[cycle][slot] is not None:
                    continue
                self.canvas.create_rectangle(
                    x,
                    y,
                    x + self.NODE_WIDTH,
                    y + self.NODE_HEIGHT,
                    outline="#d0d7de",
                    dash=(4, 3),
                    fill="#ffffff",
                )
                self.canvas.create_text(
                    x + self.NODE_WIDTH / 2,
                    y + self.NODE_HEIGHT / 2,
                    text="NOP",
                    fill="#8c959f",
                    font=("Consolas", 10),
                )
        self.canvas.create_rectangle(0, 0, width, height, outline="")

    def _draw_edges(
        self,
        analysis: ScheduleAnalysis,
        positions: dict[int, tuple[int, int, int, int]],
    ) -> None:
        offsets = {"RAW": -10, "WAR": 0, "WAW": 10}
        for edge in analysis.edges:
            if edge.source not in positions or edge.target not in positions:
                continue
            source = positions[edge.source]
            target = positions[edge.target]
            start = (
                (source[0] + source[2]) / 2 + offsets[edge.kind],
                source[3],
            )
            end = (
                (target[0] + target[2]) / 2 + offsets[edge.kind],
                target[1],
            )
            color = DEPENDENCY_COLORS[edge.kind]
            self.canvas.create_line(
                start[0],
                start[1],
                start[0],
                start[1] + 18,
                end[0],
                end[1] - 18,
                end[0],
                end[1],
                fill=color,
                width=2,
                arrow=tk.LAST,
                smooth=True,
            ) # type: ignore
            self.canvas.create_text(
                (start[0] + end[0]) / 2 + 18,
                (start[1] + end[1]) / 2,
                text=f"{edge.kind} {edge.register}",
                fill=color,
                font=("Segoe UI", 8),
            )

    def _draw_nodes(
        self,
        analysis: ScheduleAnalysis,
        positions: dict[int, tuple[int, int, int, int]],
    ) -> None:
        for index, box in positions.items():
            instruction = analysis.instructions[index]
            slot = self._slot_of(analysis, index)
            color = SLOT_COLORS[slot]
            self.canvas.create_rectangle(
                *box, fill="#ffffff", outline=color, width=2
            )
            self.canvas.create_text(
                box[0] + 10,
                box[1] + 12,
                anchor="w",
                text=f"I{index}  L{instruction.line_number}  {slot}",
                fill=color,
                font=("Segoe UI", 8),
            )
            self.canvas.create_text(
                box[0] + 10,
                box[1] + 32,
                anchor="w",
                text=instruction.label(),
                fill="#1f2328",
                font=("Consolas", 9),
            )

    def _draw_legend(self) -> None:
        x = self.LEFT_MARGIN
        y = 36 + self.canvas.bbox("all")[3] if self.canvas.bbox("all") else 40
        self.canvas.create_text(
            x,
            y,
            anchor="w",
            text="Dependencies:",
            fill="#57606a",
            font=("Segoe UI Semibold", 9),
        )
        x += 96
        for kind, color in DEPENDENCY_COLORS.items():
            self.canvas.create_line(x, y, x + 28, y, fill=color, width=3, arrow=tk.LAST)
            self.canvas.create_text(
                x + 36, y, anchor="w", text=kind, fill=color, font=("Segoe UI", 9)
            )
            x += 78

    @staticmethod
    def _slot_of(analysis: ScheduleAnalysis, index: int) -> str:
        for bundle in analysis.bundles:
            for slot, value in bundle.items():
                if value == index:
                    return slot
        raise ValueError(f"Instruction {index} is not scheduled")


class OptimizerApp(ttk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root, padding=12)
        self.root = root
        self.pack(fill=tk.BOTH, expand=True)
        root.title("RED DSP Assembly Optimizer")
        root.minsize(1180, 720)
        self._create_widgets()

    def _create_widgets(self) -> None:
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(toolbar, text="Load", command=self.load_source).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Optimize", command=self.optimize).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Button(toolbar, text="Run Optimized", command=self.run_optimized).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(toolbar, text="Save Result", command=self.save_result).pack(
            side=tk.LEFT
        )
        self.status = tk.StringVar(value="Ready")
        ttk.Label(toolbar, textvariable=self.status).pack(side=tk.RIGHT)

        panes = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True)
        editors = ttk.PanedWindow(panes, orient=tk.VERTICAL)
        self.input_text = self._create_editor(editors, "Input Assembly")
        self.output_text = self._create_editor(editors, "Optimized Assembly")
        panes.add(editors, weight=1)

        graph_frame = ttk.LabelFrame(panes, text="Dependency Graph / Slot Usage", padding=6)
        self.graph = ScheduleCanvas(graph_frame)
        self.graph.pack(fill=tk.BOTH, expand=True)
        panes.add(graph_frame, weight=2)
        self.graph.render(None)

        diagnostics = ttk.LabelFrame(self, text="Analysis")
        diagnostics.pack(fill=tk.X, pady=(8, 0))
        self.diagnostics = tk.StringVar(value="No assembly has been analyzed.")
        ttk.Label(diagnostics, textvariable=self.diagnostics).pack(
            anchor=tk.W, padx=8, pady=6
        )

        metrics_frame = ttk.LabelFrame(self, text="Efficiency Metrics", padding=6)
        metrics_frame.pack(fill=tk.X, pady=(8, 0))
        self.metrics_table = ttk.Treeview(
            metrics_frame,
            columns=("metric", "value", "description"),
            show="headings",
            height=6,
        )
        self.metrics_table.heading("metric", text="Metric")
        self.metrics_table.heading("value", text="Value")
        self.metrics_table.heading("description", text="Description")
        self.metrics_table.column("metric", width=160, stretch=False)
        self.metrics_table.column("value", width=100, anchor=tk.E, stretch=False)
        self.metrics_table.column("description", width=520, stretch=True)
        metrics_scroll = ttk.Scrollbar(
            metrics_frame, orient=tk.VERTICAL, command=self.metrics_table.yview
        )
        self.metrics_table.configure(yscrollcommand=metrics_scroll.set)
        self.metrics_table.pack(side=tk.LEFT, fill=tk.X, expand=True)
        metrics_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        execution_frame = ttk.LabelFrame(self, text="RedDSP Execution Output", padding=6)
        execution_frame.pack(fill=tk.BOTH, pady=(8, 0))
        self.execution_text = tk.Text(
            execution_frame,
            height=10,
            wrap=tk.NONE,
            state=tk.DISABLED,
            font=("Consolas", 9),
        )
        execution_y_scroll = ttk.Scrollbar(
            execution_frame, orient=tk.VERTICAL, command=self.execution_text.yview
        )
        execution_x_scroll = ttk.Scrollbar(
            execution_frame, orient=tk.HORIZONTAL, command=self.execution_text.xview
        )
        self.execution_text.configure(
            yscrollcommand=execution_y_scroll.set,
            xscrollcommand=execution_x_scroll.set,
        )
        self.execution_text.grid(row=0, column=0, sticky="nsew")
        execution_y_scroll.grid(row=0, column=1, sticky="ns")
        execution_x_scroll.grid(row=1, column=0, sticky="ew")
        execution_frame.grid_columnconfigure(0, weight=1)

    def _create_editor(self, panes: ttk.PanedWindow, title: str) -> tk.Text:
        frame = ttk.LabelFrame(panes, text=title, padding=6)
        text = tk.Text(frame, wrap=tk.NONE, undo=True, font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        panes.add(frame, weight=1)
        return text

    def load_source(self) -> None:
        path = filedialog.askopenfilename(
            title="Load RED DSP assembly",
            initialdir=str(ROOT_DIR / "asm"),
            filetypes=(("Assembly", "*.s"), ("Text", "*.txt"), ("All files", "*.*")),
        )
        if not path:
            return
        try:
            self.input_text.delete("1.0", tk.END)
            self.input_text.insert("1.0", Path(path).read_text(encoding="utf-8"))
            self.status.set(f"Loaded {Path(path).name}")
        except OSError as error:
            messagebox.showerror("Load failed", str(error), parent=self.root)

    def optimize(self) -> None:
        try:
            analysis = analyze_assembly(self.input_text.get("1.0", tk.END))
        except (OSError, ValueError) as error:
            self.status.set("Optimization failed")
            self.diagnostics.set(str(error))
            self.graph.render(None)
            messagebox.showerror("Optimization failed", str(error), parent=self.root)
            return
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert("1.0", analysis.assembly)
        self.graph.render(analysis)
        self._show_metrics(analysis.metrics)
        self.status.set("Optimization complete")
        self.diagnostics.set(
            f"{analysis.metrics['instruction_count']} instructions scheduled into "
            f"{analysis.metrics['bundle_count']} VLIW bundles, "
            f"{analysis.metrics['edge_count']} data dependencies."
        )

    def _show_metrics(self, metrics: dict[str, int | float]) -> None:
        self.metrics_table.delete(*self.metrics_table.get_children())
        for key, label, description in METRIC_LABELS:
            value = metrics[key]
            if key.endswith("_pct"):
                display_value = f"{value:.2f}%"
            elif isinstance(value, float):
                display_value = f"{value:.3f}"
            else:
                display_value = str(value)
            self.metrics_table.insert(
                "", tk.END, values=(label, display_value, description)
            )

    def run_optimized(self) -> None:
        assembly = self.output_text.get("1.0", tk.END).strip()
        if not assembly:
            self.optimize()
            assembly = self.output_text.get("1.0", tk.END).strip()
            if not assembly:
                return
        self.status.set("Running optimized assembly...")
        self.root.update_idletasks()
        try:
            result = execute_assembly(assembly + "\n")
        except (OSError, ValueError, ZeroDivisionError) as error:
            self.status.set("Execution failed")
            self._set_execution_output(f"Execution failed:\n{error}\n")
            messagebox.showerror("Execution failed", str(error), parent=self.root)
            return
        self._set_execution_output(format_execution_result(result))
        self.status.set("Execution complete")

    def _set_execution_output(self, output: str) -> None:
        self.execution_text.configure(state=tk.NORMAL)
        self.execution_text.delete("1.0", tk.END)
        self.execution_text.insert("1.0", output)
        self.execution_text.configure(state=tk.DISABLED)
        self.execution_text.see("1.0")

    def save_result(self) -> None:
        content = self.output_text.get("1.0", tk.END).strip()
        if not content:
            messagebox.showwarning(
                "No result", "Optimize assembly before saving.", parent=self.root
            )
            return
        path = filedialog.asksaveasfilename(
            title="Save optimized assembly",
            initialdir=str(ROOT_DIR / "asm"),
            initialfile="optimized.s",
            defaultextension=".s",
            filetypes=(("Assembly", "*.s"), ("All files", "*.*")),
        )
        if not path:
            return
        try:
            Path(path).write_text(content + "\n", encoding="utf-8")
            self.status.set(f"Saved {Path(path).name}")
        except OSError as error:
            messagebox.showerror("Save failed", str(error), parent=self.root)


def main() -> None:
    root = tk.Tk()
    OptimizerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
