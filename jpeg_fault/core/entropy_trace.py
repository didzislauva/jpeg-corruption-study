from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterator, Optional

from .constants.jpeg import JPEG_ZIGZAG_ORDER
from .jpeg_parse import (
    decode_dht_tables,
    decode_dqt_tables,
    decode_dri,
    decode_sof_components,
    decode_sos_components,
)
from .models import EntropyRange, Segment


@dataclass(frozen=True)
class HuffmanSymbolTrace:
    kind: str
    bits: str
    symbol: int
    start_bit: int
    end_bit: int


@dataclass(frozen=True)
class DCCoefficientTrace:
    huffman: HuffmanSymbolTrace
    category: int
    value_bits: str
    diff_value: int
    predictor_before: int
    predictor_after: int
    coefficient: int


@dataclass(frozen=True)
class ACCoefficientTrace:
    index: int
    run_length: int
    size: int
    huffman: HuffmanSymbolTrace
    value_bits: str
    coefficient: int
    symbol_hex: str
    is_eob: bool
    is_zrl: bool


@dataclass(frozen=True)
class BlockTrace:
    scan_index: int
    restart_segment_index: int
    mcu_index: int
    block_index_in_mcu: int
    component_id: int
    component_name: str
    dc_table_id: int
    ac_table_id: int
    quant_table_id: int
    scan_bit_start: int
    scan_bit_end: int
    scan_byte_start: int
    scan_byte_end: int
    start_bit_in_byte: int
    end_bit_in_byte: int
    file_byte_offsets: list[int]
    dc: DCCoefficientTrace
    ac_steps: list[ACCoefficientTrace]
    zz_coeffs: list[int]
    natural_coeffs: list[int]

    @property
    def bits_used(self) -> int:
        return self.scan_bit_end - self.scan_bit_start


@dataclass(frozen=True)
class RestartSegmentTrace:
    index: int
    marker: Optional[int]
    scan_bit_start: int
    scan_bit_end: int
    block_count: int


@dataclass(frozen=True)
class ScanTrace:
    scan_index: int
    sof_name: str
    progressive: bool
    supported: bool
    reason: str
    ss: int
    se: int
    ah: int
    al: int
    restart_interval: int
    component_ids: list[int]
    component_names: list[str]
    total_scan_bits: int
    entropy_file_start: int
    entropy_file_end: int
    blocks: list[BlockTrace]
    restart_segments: list[RestartSegmentTrace]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScanTraceChunk:
    scan_index: int
    sof_name: str
    progressive: bool
    supported: bool
    reason: str
    ss: int
    se: int
    ah: int
    al: int
    restart_interval: int
    component_ids: list[int]
    component_names: list[str]
    total_scan_bits: int
    entropy_file_start: int
    entropy_file_end: int
    blocks: list[BlockTrace]
    restart_segments: list[RestartSegmentTrace]
    done: bool


@dataclass(frozen=True)
class _FrameComponent:
    component_id: int
    component_name: str
    h_sampling: int
    v_sampling: int
    quant_table_id: int
    blocks_w: int
    blocks_h: int


@dataclass(frozen=True)
class _ScanComponent:
    component_id: int
    component_name: str
    h_sampling: int
    v_sampling: int
    quant_table_id: int
    dc_table_id: int
    ac_table_id: int
    blocks_w: int
    blocks_h: int


@dataclass(frozen=True)
class _RestartMarker:
    data_byte_index: int
    marker: int
    file_offset: int


@dataclass(frozen=True)
class _TokenizedEntropy:
    data_bytes: list[int]
    file_offsets: list[int]
    restart_markers: list[_RestartMarker]


class _BitReader:
    def __init__(self, tokenized: _TokenizedEntropy) -> None:
        self.data_bytes = tokenized.data_bytes
        self.file_offsets = tokenized.file_offsets
        self.restart_markers = tokenized.restart_markers
        self.byte_index = 0
        self.bit_index = 0

    def tell(self) -> int:
        return (self.byte_index * 8) + self.bit_index

    def bits_total(self) -> int:
        return len(self.data_bytes) * 8

    def byte_aligned(self) -> bool:
        return self.bit_index == 0

    def current_data_byte_index(self) -> int:
        return self.byte_index

    def align_to_byte(self) -> None:
        if self.bit_index == 0:
            return
        self.byte_index += 1
        self.bit_index = 0

    def read_bit(self) -> int:
        if self.byte_index >= len(self.data_bytes):
            raise EOFError("Unexpected end of entropy stream.")
        value = (self.data_bytes[self.byte_index] >> (7 - self.bit_index)) & 1
        self.bit_index += 1
        if self.bit_index == 8:
            self.byte_index += 1
            self.bit_index = 0
        return value

    def read_bits(self, count: int) -> tuple[int, str]:
        value = 0
        bits = []
        for _ in range(count):
            bit = self.read_bit()
            value = (value << 1) | bit
            bits.append("1" if bit else "0")
        return value, "".join(bits)

    def file_offsets_for_span(self, start_bit: int, end_bit: int) -> list[int]:
        if end_bit <= start_bit:
            return []
        start_byte = start_bit // 8
        end_byte = (end_bit - 1) // 8
        return self.file_offsets[start_byte:end_byte + 1]


def trace_entropy_scans(
    data: bytes,
    segments: list[Segment],
    entropy_ranges: list[EntropyRange],
) -> list[ScanTrace]:
    scans: list[ScanTrace] = []
    current_index: Optional[int] = None
    current_chunk: Optional[ScanTraceChunk] = None
    current_blocks: list[BlockTrace] = []
    current_restart_segments: list[RestartSegmentTrace] = []
    for chunk in stream_entropy_scans(data, segments, entropy_ranges):
        if current_index != chunk.scan_index:
            current_index = chunk.scan_index
            current_chunk = chunk
            current_blocks = []
            current_restart_segments = []
        current_blocks.extend(chunk.blocks)
        current_restart_segments.extend(chunk.restart_segments)
        if not chunk.done:
            continue
        scans.append(
            ScanTrace(
                scan_index=chunk.scan_index,
                sof_name=chunk.sof_name,
                progressive=chunk.progressive,
                supported=chunk.supported,
                reason=chunk.reason,
                ss=chunk.ss,
                se=chunk.se,
                ah=chunk.ah,
                al=chunk.al,
                restart_interval=chunk.restart_interval,
                component_ids=list(chunk.component_ids),
                component_names=list(chunk.component_names),
                total_scan_bits=chunk.total_scan_bits,
                entropy_file_start=chunk.entropy_file_start,
                entropy_file_end=chunk.entropy_file_end,
                blocks=list(current_blocks),
                restart_segments=list(current_restart_segments),
            )
        )
        current_index = None
        current_chunk = None
        current_blocks = []
        current_restart_segments = []
    return scans


def stream_entropy_scans(
    data: bytes,
    segments: list[Segment],
    entropy_ranges: list[EntropyRange],
    *,
    chunk_mcus: int = 256,
) -> Iterator[ScanTraceChunk]:
    tables: dict[tuple[str, int], dict[str, Any]] = {}
    frame_components: dict[int, _FrameComponent] = {}
    sof_name = ""
    restart_interval = 0
    scan_index = 0

    for seg in segments:
        if seg.payload_offset is None or seg.payload_length is None:
            continue
        payload = data[seg.payload_offset:seg.payload_offset + seg.payload_length]
        if seg.name.startswith("SOF"):
            sof_name = seg.name
            frame_components = _frame_components_from_sof(payload)
            continue
        if seg.name == "DHT":
            for table in decode_dht_tables(payload):
                tables[(str(table["class"]), int(table["id"]))] = table
            continue
        if seg.name == "DQT":
            decode_dqt_tables(payload)
            continue
        if seg.name == "DRI":
            info = decode_dri(payload)
            restart_interval = int(info["restart_interval"]) if info else 0
            continue
        if seg.name != "SOS":
            continue
        if scan_index >= len(entropy_ranges):
            break
        yield from _stream_scan(
            data=data,
            payload=payload,
            entropy_range=entropy_ranges[scan_index],
            scan_index=scan_index,
            sof_name=sof_name,
            frame_components=frame_components,
            tables=tables,
            restart_interval=restart_interval,
            chunk_mcus=chunk_mcus,
        )
        scan_index += 1
    


def format_scan_trace_text(scans: list[ScanTrace]) -> str:
    lines: list[str] = []
    for scan in scans:
        lines.append(f"Scan {scan.scan_index}")
        lines.append(
            f"  SOF={scan.sof_name or '<unknown>'} supported={scan.supported} progressive={scan.progressive}"
        )
        lines.append(
            f"  Components={', '.join(scan.component_names) or '<none>'} "
            f"Ss={scan.ss} Se={scan.se} Ah={scan.ah} Al={scan.al} DRI={scan.restart_interval}"
        )
        lines.append(
            f"  Entropy bytes={scan.entropy_file_start:08X}..{max(scan.entropy_file_start, scan.entropy_file_end - 1):08X} "
            f"total_bits={scan.total_scan_bits} blocks={len(scan.blocks)}"
        )
        if not scan.supported:
            lines.append(f"  Note: {scan.reason}")
            continue
        for restart in scan.restart_segments:
            marker = f"RST{restart.marker - 0xD0}" if restart.marker is not None else "none"
            lines.append(
                f"  Restart segment {restart.index}: marker_before={marker} "
                f"bits=[{restart.scan_bit_start},{restart.scan_bit_end}) blocks={restart.block_count}"
            )
        for block in scan.blocks:
            lines.append(
                f"  MCU {block.mcu_index} block {block.block_index_in_mcu} "
                f"{block.component_name}: bits=[{block.scan_bit_start},{block.scan_bit_end}) "
                f"bytes={block.scan_byte_start}..{block.scan_byte_end} "
                f"file={_format_file_offsets(block.file_byte_offsets)} "
                f"dc={block.dc.coefficient}"
            )
            lines.append(
                f"    Tables: DC={block.dc_table_id} AC={block.ac_table_id} QT={block.quant_table_id}"
            )
            lines.append(
                f"    DC huff={block.dc.huffman.bits} category={block.dc.category} "
                f"value_bits={block.dc.value_bits or '-'} diff={block.dc.diff_value} "
                f"pred={block.dc.predictor_before}->{block.dc.predictor_after}"
            )
            if not block.ac_steps:
                lines.append("    AC: <none>")
            for step in block.ac_steps:
                lines.append(
                    f"    AC k={step.index} run={step.run_length} size={step.size} "
                    f"sym=0x{step.symbol_hex} huff={step.huffman.bits} "
                    f"value_bits={step.value_bits or '-'} coeff={step.coefficient} "
                    f"EOB={step.is_eob} ZRL={step.is_zrl}"
                )
            lines.append(
                "    ZZ: " + " ".join(str(v) for v in block.zz_coeffs[:16]) + (" ..." if len(block.zz_coeffs) > 16 else "")
            )
    return "\n".join(lines) + ("\n" if lines else "")


def _stream_scan(
    *,
    data: bytes,
    payload: bytes,
    entropy_range: EntropyRange,
    scan_index: int,
    sof_name: str,
    frame_components: dict[int, _FrameComponent],
    tables: dict[tuple[str, int], dict[str, Any]],
    restart_interval: int,
    chunk_mcus: int,
) -> Iterator[ScanTraceChunk]:
    scan_components, ss, se, ah, al = _scan_components_from_sos(payload, frame_components)
    component_ids = [component.component_id for component in scan_components]
    component_names = [component.component_name for component in scan_components]
    tokenized = _tokenize_entropy_range(data, entropy_range)
    progressive = sof_name == "SOF2" or ss != 0 or se != 63 or ah != 0 or al != 0
    if not frame_components:
        yield _unsupported_scan_chunk(
            scan_index, sof_name, progressive, "Missing SOF metadata before SOS.", ss, se, ah, al,
            restart_interval, component_ids, component_names, entropy_range, tokenized
        )
        return
    if sof_name != "SOF0":
        yield _unsupported_scan_chunk(
            scan_index, sof_name, progressive, f"{sof_name} tracing is not implemented yet.", ss, se, ah, al,
            restart_interval, component_ids, component_names, entropy_range, tokenized
        )
        return
    if progressive:
        yield _unsupported_scan_chunk(
            scan_index, sof_name, progressive, "Progressive/refinement scan tracing is not implemented yet.",
            ss, se, ah, al, restart_interval, component_ids, component_names, entropy_range, tokenized
        )
        return
    meta = dict(
        scan_index=scan_index,
        sof_name=sof_name,
        progressive=progressive,
        ss=ss,
        se=se,
        ah=ah,
        al=al,
        restart_interval=restart_interval,
        component_ids=component_ids,
        component_names=component_names,
        total_scan_bits=len(tokenized.data_bytes) * 8,
        entropy_file_start=entropy_range.start,
        entropy_file_end=entropy_range.end,
    )
    try:
        yield from _stream_baseline_scan(
            scan_index=scan_index,
            tokenized=tokenized,
            scan_components=scan_components,
            tables=tables,
            restart_interval=restart_interval,
            frame_components=frame_components,
            chunk_mcus=chunk_mcus,
            meta=meta,
        )
    except Exception as exc:
        reason = f"Baseline trace failed: {exc}"
        yield _unsupported_scan_chunk(
            scan_index, sof_name, progressive, reason, ss, se, ah, al,
            restart_interval, component_ids, component_names, entropy_range, tokenized
        )
        return


def _unsupported_scan_chunk(
    scan_index: int,
    sof_name: str,
    progressive: bool,
    reason: str,
    ss: int,
    se: int,
    ah: int,
    al: int,
    restart_interval: int,
    component_ids: list[int],
    component_names: list[str],
    entropy_range: EntropyRange,
    tokenized: _TokenizedEntropy,
) -> ScanTraceChunk:
    return ScanTraceChunk(
        scan_index=scan_index,
        sof_name=sof_name,
        progressive=progressive,
        supported=False,
        reason=reason,
        ss=ss,
        se=se,
        ah=ah,
        al=al,
        restart_interval=restart_interval,
        component_ids=component_ids,
        component_names=component_names,
        total_scan_bits=len(tokenized.data_bytes) * 8,
        entropy_file_start=entropy_range.start,
        entropy_file_end=entropy_range.end,
        blocks=[],
        restart_segments=[],
        done=True,
    )


def _frame_components_from_sof(payload: bytes) -> dict[int, _FrameComponent]:
    if len(payload) < 6:
        return {}
    height = int.from_bytes(payload[1:3], "big")
    width = int.from_bytes(payload[3:5], "big")
    decoded = decode_sof_components(payload)
    if not decoded:
        return {}
    max_h = max(component["h_sampling"] for component in decoded) or 1
    max_v = max(component["v_sampling"] for component in decoded) or 1
    components: dict[int, _FrameComponent] = {}
    for component in decoded:
        comp_id = int(component["id"])
        h_sampling = int(component["h_sampling"])
        v_sampling = int(component["v_sampling"])
        components[comp_id] = _FrameComponent(
            component_id=comp_id,
            component_name=_component_name(comp_id, len(decoded)),
            h_sampling=h_sampling,
            v_sampling=v_sampling,
            quant_table_id=int(component["quant_table_id"]),
            blocks_w=(width * h_sampling + (8 * max_h) - 1) // (8 * max_h),
            blocks_h=(height * v_sampling + (8 * max_v) - 1) // (8 * max_v),
        )
    return components


def _scan_components_from_sos(
    payload: bytes,
    frame_components: dict[int, _FrameComponent],
) -> tuple[list[_ScanComponent], int, int, int, int]:
    if len(payload) < 4:
        return [], 0, 0, 0, 0
    decoded = decode_sos_components(payload)
    ns = payload[0]
    ss = payload[1 + (2 * ns)]
    se = payload[2 + (2 * ns)]
    ahal = payload[3 + (2 * ns)]
    ah = ahal >> 4
    al = ahal & 0x0F
    components: list[_ScanComponent] = []
    for component in decoded:
        frame_component = frame_components.get(int(component["id"]))
        if frame_component is None:
            continue
        components.append(
            _ScanComponent(
                component_id=frame_component.component_id,
                component_name=frame_component.component_name,
                h_sampling=frame_component.h_sampling,
                v_sampling=frame_component.v_sampling,
                quant_table_id=frame_component.quant_table_id,
                dc_table_id=int(component["dc_table_id"]),
                ac_table_id=int(component["ac_table_id"]),
                blocks_w=frame_component.blocks_w,
                blocks_h=frame_component.blocks_h,
            )
        )
    return components, ss, se, ah, al


def _tokenize_entropy_range(data: bytes, entropy_range: EntropyRange) -> _TokenizedEntropy:
    values: list[int] = []
    offsets: list[int] = []
    restart_markers: list[_RestartMarker] = []
    i = entropy_range.start
    while i < entropy_range.end:
        byte = data[i]
        if byte != 0xFF:
            values.append(byte)
            offsets.append(i)
            i += 1
            continue
        if i + 1 >= entropy_range.end:
            values.append(byte)
            offsets.append(i)
            break
        nxt = data[i + 1]
        if nxt == 0x00:
            values.append(0xFF)
            offsets.append(i)
            i += 2
            continue
        if 0xD0 <= nxt <= 0xD7:
            restart_markers.append(_RestartMarker(len(values), nxt, i))
            i += 2
            continue
        values.append(byte)
        offsets.append(i)
        i += 1
    return _TokenizedEntropy(values, offsets, restart_markers)


def _stream_baseline_scan(
    *,
    scan_index: int,
    tokenized: _TokenizedEntropy,
    scan_components: list[_ScanComponent],
    tables: dict[tuple[str, int], dict[str, Any]],
    restart_interval: int,
    frame_components: dict[int, _FrameComponent],
    chunk_mcus: int,
    meta: dict[str, Any],
) -> Iterator[ScanTraceChunk]:
    if not scan_components:
        yield ScanTraceChunk(supported=True, reason="", blocks=[], restart_segments=[], done=True, **meta)
        return
    reader = _BitReader(tokenized)
    dc_predictors = {component_id: 0 for component_id in frame_components}
    blocks: list[BlockTrace] = []
    restart_segments: list[RestartSegmentTrace] = []
    chunk_blocks: list[BlockTrace] = []
    chunk_restart_segments: list[RestartSegmentTrace] = []
    restart_markers = {marker.data_byte_index: marker for marker in tokenized.restart_markers}
    restart_segment_index = 0
    restart_segment_start = 0
    restart_segment_marker: Optional[int] = None
    block_plan, mcu_count = _mcu_block_plan(scan_components)
    chunk_mcus = max(1, int(chunk_mcus))

    for mcu_index in range(mcu_count):
        if restart_interval and mcu_index > 0 and (mcu_index % restart_interval) == 0:
            reader.align_to_byte()
        if reader.byte_aligned():
            marker = restart_markers.get(reader.current_data_byte_index())
            if marker is not None:
                restart_trace = RestartSegmentTrace(
                    index=restart_segment_index,
                    marker=restart_segment_marker,
                    scan_bit_start=restart_segment_start,
                    scan_bit_end=reader.tell(),
                    block_count=sum(1 for block in blocks if block.restart_segment_index == restart_segment_index),
                )
                restart_segments.append(restart_trace)
                chunk_restart_segments.append(restart_trace)
                restart_segment_index += 1
                restart_segment_start = reader.tell()
                restart_segment_marker = marker.marker
                dc_predictors = {component_id: 0 for component_id in frame_components}
        for block_index_in_mcu, component in enumerate(block_plan):
            if reader.tell() >= reader.bits_total():
                break
            block = _decode_block(
                reader=reader,
                scan_index=scan_index,
                restart_segment_index=restart_segment_index,
                mcu_index=mcu_index,
                block_index_in_mcu=block_index_in_mcu,
                component=component,
                tables=tables,
                dc_predictors=dc_predictors,
            )
            blocks.append(block)
            chunk_blocks.append(block)
        if reader.tell() >= reader.bits_total():
            break
        if chunk_blocks and ((mcu_index + 1) % chunk_mcus) == 0:
            yield ScanTraceChunk(
                supported=True,
                reason="",
                blocks=list(chunk_blocks),
                restart_segments=list(chunk_restart_segments),
                done=False,
                **meta,
            )
            chunk_blocks.clear()
            chunk_restart_segments.clear()
    restart_trace = RestartSegmentTrace(
        index=restart_segment_index,
        marker=restart_segment_marker,
        scan_bit_start=restart_segment_start,
        scan_bit_end=reader.tell(),
        block_count=sum(1 for block in blocks if block.restart_segment_index == restart_segment_index),
    )
    restart_segments.append(restart_trace)
    chunk_restart_segments.append(restart_trace)
    yield ScanTraceChunk(
        supported=True,
        reason="",
        blocks=list(chunk_blocks),
        restart_segments=list(chunk_restart_segments),
        done=True,
        **meta,
    )


def _mcu_block_plan(scan_components: list[_ScanComponent]) -> tuple[list[_ScanComponent], int]:
    if len(scan_components) == 1:
        component = scan_components[0]
        return [component], component.blocks_w * component.blocks_h
    plan: list[_ScanComponent] = []
    for component in scan_components:
        plan.extend([component] * (component.h_sampling * component.v_sampling))
    mcu_cols = max(
        1,
        max((component.blocks_w + component.h_sampling - 1) // component.h_sampling for component in scan_components),
    )
    mcu_rows = max(
        1,
        max((component.blocks_h + component.v_sampling - 1) // component.v_sampling for component in scan_components),
    )
    return plan, mcu_cols * mcu_rows


def _decode_block(
    *,
    reader: _BitReader,
    scan_index: int,
    restart_segment_index: int,
    mcu_index: int,
    block_index_in_mcu: int,
    component: _ScanComponent,
    tables: dict[tuple[str, int], dict[str, Any]],
    dc_predictors: dict[int, int],
) -> BlockTrace:
    start_bit = reader.tell()
    dc_trace = _decode_dc_coefficient(reader, component, tables, dc_predictors)
    coeffs = [0] * 64
    coeffs[0] = dc_trace.coefficient
    ac_steps = _decode_ac_coefficients(reader, component, tables, coeffs)
    end_bit = reader.tell()
    file_offsets = reader.file_offsets_for_span(start_bit, end_bit)
    natural = _natural_coeffs(coeffs)
    return BlockTrace(
        scan_index=scan_index,
        restart_segment_index=restart_segment_index,
        mcu_index=mcu_index,
        block_index_in_mcu=block_index_in_mcu,
        component_id=component.component_id,
        component_name=component.component_name,
        dc_table_id=component.dc_table_id,
        ac_table_id=component.ac_table_id,
        quant_table_id=component.quant_table_id,
        scan_bit_start=start_bit,
        scan_bit_end=end_bit,
        scan_byte_start=start_bit // 8,
        scan_byte_end=max(start_bit // 8, (end_bit - 1) // 8),
        start_bit_in_byte=start_bit % 8,
        end_bit_in_byte=(end_bit - 1) % 8 if end_bit > start_bit else start_bit % 8,
        file_byte_offsets=file_offsets,
        dc=dc_trace,
        ac_steps=ac_steps,
        zz_coeffs=coeffs,
        natural_coeffs=natural,
    )


def _decode_dc_coefficient(
    reader: _BitReader,
    component: _ScanComponent,
    tables: dict[tuple[str, int], dict[str, Any]],
    dc_predictors: dict[int, int],
) -> DCCoefficientTrace:
    huffman = _read_huffman_symbol(reader, tables, "DC", component.dc_table_id)
    category = huffman.symbol
    value, bits = reader.read_bits(category) if category else (0, "")
    diff = _decode_signed(value, category)
    predictor_before = dc_predictors.get(component.component_id, 0)
    predictor_after = predictor_before + diff
    dc_predictors[component.component_id] = predictor_after
    return DCCoefficientTrace(
        huffman=huffman,
        category=category,
        value_bits=bits,
        diff_value=diff,
        predictor_before=predictor_before,
        predictor_after=predictor_after,
        coefficient=predictor_after,
    )


def _decode_ac_coefficients(
    reader: _BitReader,
    component: _ScanComponent,
    tables: dict[tuple[str, int], dict[str, Any]],
    coeffs: list[int],
) -> list[ACCoefficientTrace]:
    steps: list[ACCoefficientTrace] = []
    k = 1
    while k < 64:
        huffman = _read_huffman_symbol(reader, tables, "AC", component.ac_table_id)
        symbol = huffman.symbol
        if symbol == 0x00:
            steps.append(
                ACCoefficientTrace(
                    index=k,
                    run_length=0,
                    size=0,
                    huffman=huffman,
                    value_bits="",
                    coefficient=0,
                    symbol_hex=f"{symbol:02X}",
                    is_eob=True,
                    is_zrl=False,
                )
            )
            break
        if symbol == 0xF0:
            steps.append(
                ACCoefficientTrace(
                    index=k,
                    run_length=16,
                    size=0,
                    huffman=huffman,
                    value_bits="",
                    coefficient=0,
                    symbol_hex=f"{symbol:02X}",
                    is_eob=False,
                    is_zrl=True,
                )
            )
            k += 16
            continue
        run_length = symbol >> 4
        size = symbol & 0x0F
        k += run_length
        if k >= 64:
            break
        value, bits = reader.read_bits(size) if size else (0, "")
        coefficient = _decode_signed(value, size)
        coeffs[k] = coefficient
        steps.append(
            ACCoefficientTrace(
                index=k,
                run_length=run_length,
                size=size,
                huffman=huffman,
                value_bits=bits,
                coefficient=coefficient,
                symbol_hex=f"{symbol:02X}",
                is_eob=False,
                is_zrl=False,
            )
        )
        k += 1
    return steps


def _read_huffman_symbol(
    reader: _BitReader,
    tables: dict[tuple[str, int], dict[str, Any]],
    table_class: str,
    table_id: int,
) -> HuffmanSymbolTrace:
    table = tables.get((table_class, table_id))
    if table is None:
        raise ValueError(f"Missing {table_class} Huffman table {table_id}.")
    lookup = _huffman_lookup(table)
    start_bit = reader.tell()
    code = 0
    bits = []
    for length in range(1, 17):
        bit = reader.read_bit()
        code = (code << 1) | bit
        bits.append("1" if bit else "0")
        symbol = lookup.get((length, code))
        if symbol is not None:
            return HuffmanSymbolTrace(
                kind=table_class.lower(),
                bits="".join(bits),
                symbol=int(symbol),
                start_bit=start_bit,
                end_bit=reader.tell(),
            )
    raise ValueError(f"Unable to decode {table_class} Huffman symbol from bits {''.join(bits)}.")


def _huffman_lookup(table: dict[str, Any]) -> dict[tuple[int, int], int]:
    return {
        (int(code["length"]), int(code["code"])): int(code["symbol"])
        for code in list(table.get("codes", []))
    }


def _decode_signed(value: int, size: int) -> int:
    if size == 0:
        return 0
    threshold = 1 << (size - 1)
    if value >= threshold:
        return value
    return value - ((1 << size) - 1)


def _natural_coeffs(zz_coeffs: list[int]) -> list[int]:
    natural = [0] * 64
    for idx, coeff in enumerate(zz_coeffs[:64]):
        natural[JPEG_ZIGZAG_ORDER[idx]] = coeff
    return natural


def _format_file_offsets(offsets: list[int]) -> str:
    if not offsets:
        return "<none>"
    if len(offsets) == 1:
        return f"0x{offsets[0]:08X}"
    return f"0x{offsets[0]:08X}..0x{offsets[-1]:08X}"


def _component_name(component_id: int, total_components: int) -> str:
    if total_components == 1 and component_id == 1:
        return "Y"
    names = {1: "Y", 2: "Cb", 3: "Cr", 4: "I", 5: "Q"}
    return names.get(component_id, f"C{component_id}")
