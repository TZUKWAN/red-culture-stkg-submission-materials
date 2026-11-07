from __future__ import annotations

from pathlib import Path
import csv
import re
import shutil
import zipfile
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn

ROOT = Path(r"D:\REDCULTUREDATA")
BASE = ROOT / "revision_output" / "20261015_round3"
SRC = BASE / "working" / "上一轮修订稿.docx"
OUT = BASE / "deliverables" / "论文_全文深度修订稿.docx"
FIGDIR = BASE / "working"

FU_REFERENCE = (
    '付翔, 黄金宇, 秦一凡, 等. 面向强规范领域的知识图谱增强检索与原文校验可信生成方法[J/OL]. '
    '数据分析与知识发现, 2026-09-17. https://link.cnki.net/urlid/10.1478.G2.20260917.1335.008.'
)


def replace_text(p, text: str) -> None:
    if p.runs:
        p.runs[0].text = text
        for r in p.runs[1:]:
            r.text = ''
    else:
        p.add_run(text)


def insert_before(anchor, text: str, style=None):
    p = anchor.insert_paragraph_before(text)
    if style is not None:
        p.style = style
    return p


def find_prefix(doc, prefix: str):
    return next((p for p in doc.paragraphs if p.text.strip().startswith(prefix)), None)


def find_exact(doc, text: str):
    return next((p for p in doc.paragraphs if p.text.strip() == text), None)


def replace_media(docx_path: Path, replacements: dict[str, Path]) -> None:
    tmp = docx_path.with_suffix('.media.tmp.docx')
    with zipfile.ZipFile(docx_path, 'r') as zin, zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename in {f'word/media/{k}' for k in replacements}:
                key = item.filename.split('/')[-1]
                data = replacements[key].read_bytes()
            zout.writestr(item, data)
    tmp.replace(docx_path)


def add_equation_numbers(doc) -> int:
    """Restore visible right-hand numbers for legacy OLE equation paragraphs.

    The converted .docx retains each equation as an editable OLE object, but
    its trailing Word field is empty.  Preserve the OLE object and the tab
    stop, remove the empty field runs, and append a literal number.
    """
    count = 0
    for p in doc.paragraphs:
        ppr = p._p.pPr
        style_id = ppr.pStyle.get(qn('w:val')) if ppr is not None and ppr.pStyle is not None else None
        if style_id != 'MTDisplayEquation1' or not p._p.xpath('.//w:object'):
            continue
        children = list(p._p)
        object_idx = next((i for i, c in enumerate(children) if c.xpath('.//w:object')), None)
        if object_idx is None:
            continue
        tab_idx = next((i for i in range(object_idx + 1, len(children)) if children[i].xpath('.//w:tab')), None)
        if tab_idx is None:
            tab_idx = object_idx
        for child in list(p._p)[tab_idx + 1:]:
            if child.tag == qn('w:r'):
                p._p.remove(child)
        count += 1
        run = p.add_run(f'({count})')
        run.font.name = 'Times New Roman'
        run.font.size = Pt(10)
    return count


def keep_figure_caption_together(doc, caption: str) -> bool:
    """Keep a figure paragraph and its bilingual caption on one page."""
    paras = doc.paragraphs
    for i, p in enumerate(paras):
        if p.text.strip() == caption and i > 0:
            paras[i - 1].paragraph_format.keep_with_next = True
            p.paragraph_format.keep_with_next = True
            return True
    return False


def main():
    doc = Document(SRC)
    changes = []

    # Remove repeated defensive wording while keeping the denominator and scope.
    p = find_prefix(doc, '摘要:')
    if p:
        t = p.text.replace('复杂历史语境下的跨来源专家核验仍需扩展。', '后续工作应扩展跨来源证据组织与复杂语义限定识别。')
        replace_text(p, t); changes.append('abstract_limitations')

    p = find_prefix(doc, 'Abstract:')
    if p:
        t = p.text.replace('cross-source expert verification in complex historical contexts requires further extension.', 'cross-source evidence organization and complex semantic-scope identification require further development.')
        replace_text(p, t); changes.append('abstract_limitations_en')

    p = find_prefix(doc, '研究贡献主要包括三个方面')
    if p:
        replace_text(p, '研究贡献主要包括三个方面：（1）提出以规范断言为核心的历史知识质量控制框架，将实体身份、关系语义及时空作用域规范化纳入同一语义约束过程，明确局部转换如何共同形成完整命题；（2）构建结构约束与断言级证据核验协同的级联准入机制，以严格、上下文和未决三类状态组织候选知识，并把来源定位、规范化和证据门连接为可追溯准入链；（3）从准入侧和门外侧同时评价质量，分别报告强共识条件下的支持精度与潜在严格准入机会，用质量—覆盖关系说明选择性控制的实际边界。')
        changes.append('contributions_rewritten')

    # Use all previously unused bibliography items where they directly support the text.
    p = find_prefix(doc, '历史文献知识图谱通常')
    if p:
        replace_text(p, '历史文献知识图谱通常以实体、关系和事件抽取为基础，通过实体归一、关系规范化及时空组织，将分散于文本中的历史信息转化为结构化知识。近年来，大语言模型提升了复杂历史文本中候选知识的发现能力，但抽取结果仍需经过多环节语义加工才能形成可稳定使用的图谱知识。实体提及需要映射到规范身份，自然语言关系需要转换为受控谓词，时间和地点还需明确其语义角色和归属对象。相关研究已从数字人文知识组织、文化遗产图谱生成和大语言模型—知识图谱协同等方面展开讨论[1-3,8-13]。长江流域红色档案的跨区域协同开发及国家文化公园建设，也使跨区域资料的统一组织具有现实需求[7,14-15]。'); changes.append('citation_background_reallocated')
    p = find_prefix(doc, '历史知识规范化主要涉及对象身份')
    if p:
        replace_text(p, '历史知识规范化主要涉及对象身份、关系语义和结构约束。实体层面的研究通过规范标目、实体链接和命名实体消歧，将不同文本中的实体提及映射到统一对象[16-20,37,40]；关系规范化则处理开放关系表达与受控谓词体系之间的对应[21-23,38-39]。近年来，开放谓词规范化进一步引入关系定义和模式映射，SHACL属性约束、校验形状及实体类型约束等方法则利用定义域、值域和端点类型检查关系实例的结构一致性[29-31,41-44]。'); changes.append('citation_normalization_reallocated')
    p = find_prefix(doc, '实体归一结果决定关系端点')
    if p:
        replace_text(p, '实体归一结果决定关系端点的实际指向，谓词映射限定关系语义及其适用类型，时间和地点的归属则依赖已经确定的实体、事件或关系对象。事件边界识别误差会继续影响后续关系分类，迭代学习研究也观察到早期错误在后续处理中累积的现象[23-28,33-34,42-43]。前序判断对后续处理对象的持续影响，使单个环节的性能与最终规范断言的质量对应不同的评价对象。'); changes.append('citation_relation_reallocated')

    p = find_prefix(doc, '针对单项判断中的不确定性')
    if p:
        replace_text(p, p.text.rstrip('。') + ' [4,25-26,41]。'); changes.append('citation_selective_prediction')

    # Direct comparison with the supplied Fu Xiang paper, keeping control object,
    # stage and output distinct.
    p = find_prefix(doc, '从知识与史料之间的关联深度看')
    if p:
        replace_text(p, '从知识与史料之间的关联深度看，相关研究大体形成了来源追溯、原文定位和语义支持三个层次。来源链、文献标识和原句记录等方法用于保存结构化知识的文献出处及加工过程；进一步的原文定位将知识关联到具体文本位置；事实一致性评价和知识验证则利用原文片段或检索证据判断具体命题是否成立。付翔等[47]将图谱—原文联合定位和逐子句校验用于生成后的回答，控制对象是回答内容及规范强度；本文控制对象是规范断言，控制阶段是规范知识形成与入图准入阶段，实体指称、关系映射及时空归属共同确定待入图命题，证据核验决定其知识状态。两者都要求回到原文，但分处回答生成与知识准入两个阶段。基于此，本文将来源定位、规范化和证据门组织为准入链，而不把回答校验方法直接移植到历史断言[35-36,47]。')
        changes.append('fuxiang_direct_comparison')

    # State the chapter-3 scope and strict-layer definition before equations.
    p31 = find_exact(doc, '3.1  规范断言表示与知识状态')
    if p31:
        insert_before(p31, '本文以历史文献生成的候选记录为输入，以附有来源信息和证据状态的规范断言为输出。实体、关系及时空规范化确定命题的对象、联系和限定范围，结构检查筛选具备证据核验条件的候选，语义核验进一步决定其准入状态。各环节通过统一断言标识关联，保存局部判断与完整命题之间的对应关系。')
        p40 = next((p for p in doc.paragraphs if p.text.strip().startswith('设历史文献集合为D')), None)
        if p40:
            insert_before(p40, '严格层指满足前置结构条件并经证据门接受的规范断言；完全支持和部分支持均保留支持等级，但部分支持只有在固定谓词准入政策允许时进入严格层。部分支持但不在该政策内、以及证据不足的记录进入上下文层；不支持、冲突和无证据的记录进入未决层。')
        changes.append('chapter3_scope_and_strict_definition')

    # Make full-production model roles explicit and separate from local strategy tests.
    p41 = find_exact(doc, '4.1  数据来源与实验设置')
    if p41:
        p_data = next((p for p in doc.paragraphs if p.text.strip().startswith('本文选取长江流域13个省级行政区域')), None)
        p_plan = next((p for p in doc.paragraphs if p.text.strip().startswith('全库实验比较前置严格候选')), None)
        if p_data and p_plan:
            insert_before(p_plan, '全库生产使用冻结的规则、局部分类器和证据门：证据门由 qwen3.5-4b（reasoning off，temperature=0）执行，最终层级依据证据门输出确定。全库证据审计由 gpt-oss-20b 与 qwen/qwen3-8b 两个独立裁判完成，裁判不读取另一裁判结论或知识层级。')
            insert_before(next((p for p in doc.paragraphs if p.text.strip().startswith('质量评价以规范断言')), None), '局部实验使用独立的固定参考集合。实体类型任务共382条，以B2冻结分类器为基础预测，风险路由使用验证集选择的DecisionTree_max_depth4，升级裁决调用openai/gpt-oss-20b；208条时空作用域任务按转换类型学习改写或保留规则。局部实验用于比较策略配置，不把其升级调用率或参考一致率外推为全库生产结果。')
            changes.append('model_roles_reordered_and_local_roles')

    # Replace the traceability case with the actual raw candidate / normalized assertion pair.
    p = find_prefix(doc, '上饶中心县委案例则体现了')
    if p:
        replace_text(p, '上饶中心县委案例体现了规范化如何改变完整命题的含义。该例包含两种性质不同的转换：主体由地点调整为组织，修正了对象类别；关系由“活动范围”映射为“驻扎于”，则把活动地域表述转化为具体驻地判断，增加了关系成立所需的证据要求。相关引文确认了组织组建及其别称，也记述了党组织恢复活动，但没有给出“管村乡龙源、仓坞等村”为具体驻地的依据。因此，对象类型得到修正，并不意味着关系映射同时获得证实，二者需要在完整断言中分别接受证据检查。该条在 V2 中的 strict_semantic 是结构准入阶段的状态；进入证据门后，五档判定为部分支持，最终层按固定谓词政策归入上下文层。')
        changes.append('traceable_normalization_case_reframed')

    p = find_prefix(doc, '该指标是强共识条件下的选择性支持精度')
    if p:
        replace_text(p, p.text.replace('该指标是强共识条件下的选择性支持精度，不代表全库完整事实准确率。', '该指标把支持程度与评价分歧放在同一强共识条件口径下呈现。'))
        changes.append('remove_repeated_metric_caveat')

    p = find_prefix(doc, '选择性策略在45.16%的覆盖范围内')
    if p:
        replace_text(p, p.text.replace('该结果支持质量—覆盖取舍的解释，不构成对所有时空归属的普遍改写规则。', '该结果支持按转换类型和参考证据分别维护作用域策略。'))
        changes.append('scope_wording')

    p = find_prefix(doc, '经证据核验筛选后，最终严格层的条件支持精度')
    if p:
        replace_text(p, p.text.replace('该指标是强共识条件下的选择性支持精度，不代表全库完整事实准确率。', '该指标把支持程度与评价分歧放在同一强共识条件口径下呈现。'))
        changes.append('remove_repeated_final_metric_caveat')

    p = find_prefix(doc, '规范化后的知识组织需要同时保留对象间的联系')
    if p:
        replace_text(p, '规范化后的知识组织需要同时保留对象间的联系、联系的语义类型和各项命题的证据状态。图9直接取自T34严格层边表，选取以“南昌起义”为客体的12条代表性边：组织关系连接中国共产党和周恩来，领导关系连接刘伯承、前敌委员会、叶挺、周恩来和朱德，参与关系连接二十军的教导团、余增生、傅光夏、冉聿修和刘久成。图中箭头均由主体指向事件，节点颜色表示主体或客体类型。')
        changes.append('figure9_text_aligned')

    p = find_prefix(doc, '若将上述边统一表示为“相关”')
    if p:
        replace_text(p, '图9不承担空间粒度分析，只用于说明同一事件中的角色关系如何被区分。周恩来同时出现在组织和领导两类边中，说明同一主体可以在不同断言中承担不同角色；把这些边统一表示为“相关”会丢失角色语义，也会削弱按角色检索和解释的能力。图中组织、领导和参与三类关系均以南昌起义为客体，方向和谓词来自同一严格层边表，因此事件框架的汇聚作用与断言的角色约束能够在同一网络中对应。')
        changes.append('figure9_analysis_aligned')

    set_caption = {
        '图9  “南昌起义”事件的角色关系节选': '图9  “南昌起义”严格层事件关系网络（T34边表节选）',
        'Fig. 9 Selected Role Relations of the Nanchang Uprising Event': 'Fig. 9 Strict-Layer Event Relation Network of the Nanchang Uprising (T34 Excerpt)',
    }
    for old, new in set_caption.items():
        q = find_exact(doc, old)
        if q:
            replace_text(q, new); changes.append('figure9_caption')

    p = find_prefix(doc, '基于长江流域13个省级行政区域983册中共党史文献的实验结果表明')
    if p:
        replace_text(p, '基于长江流域13个省级行政区域983册中共党史文献的实验结果表明，历史知识规范化后的结构一致性并不能直接保证完整断言获得史料支持，知识准入仍需进一步考察关系内容及时空限定是否得到原文支撑。通过引入断言级证据核验，本文能够将满足既定结构、证据和谓词政策的记录归入严格层，并保留相应支持等级；需要补充语境的记录进入上下文层，存在冲突或无法形成稳定判断的记录进入未决层。这样，知识图谱不仅保存对象之间的关联关系，同时保留关联成立的依据和确定程度。实验结果进一步表明，历史知识中的不确定性来源具有任务差异，实体指称、关系解释及时空归属需要采用不同的选择性控制策略，而非简单扩大自动接受范围。')
        changes.append('conclusion_strict_definition')

    p = find_prefix(doc, '实体类型实验包含382条任务')
    if p:
        replace_text(p, '实体类型实验包含382条任务，划分为254条开发样本、66条验证样本和62条测试样本。以B2冻结分类器作为基础预测，风险路由模型为验证集选择的DecisionTree_max_depth4，升级裁决模型为openai/gpt-oss-20b；预测器消融另比较字符TF-IDF、nomic-embed嵌入和二者融合三种局部配置。测试采用排除裁判B标签后形成的共识参考，即leave-B-out参考，其中48条具有有效标签。表3在同一参考集合上比较规则、分类器、大模型及其组合，并考察类型接受条件与风险路由的作用。')
        changes.append('type_model_roles')

    # Add the supplied paper as reference [47]. Keep the publication metadata
    # visibly pending rather than silently inventing volume/issue/pages.
    ref_heading = find_exact(doc, '参考文献：')
    author_anchor = find_prefix(doc, '通讯作者（Corresponding author）')
    if ref_heading and author_anchor:
        author_anchor.insert_paragraph_before(f'[47] {FU_REFERENCE}')
        changes.append('reference_47_added')

    # The converted source carries several empty declaration paragraphs that
    # push the support-data statement onto an almost blank final page.
    author_anchor = find_prefix(doc, '通讯作者（Corresponding author）')
    data_anchor = find_prefix(doc, '支撑数据：')
    if author_anchor and data_anchor:
        started = False
        for p in list(doc.paragraphs):
            if p is author_anchor:
                started = True
                continue
            if p is data_anchor:
                break
            if started and not p.text.strip():
                p._element.getparent().remove(p._element)
        changes.append('trim_declaration_spacing')

    # Ensure all bibliography entries are referenced in body text. The new
    # citations cover the 15 items previously unused by the first revision.
    # Cite [47] in the comparison paragraph above; no bibliography entry is
    # removed so existing numbering remains stable.

    # Tables: repeat headers and prevent row splitting.
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    for table in doc.tables:
        if table.rows:
            trPr = table.rows[0]._tr.get_or_add_trPr()
            if not trPr.xpath('./w:tblHeader'):
                th = OxmlElement('w:tblHeader'); th.set(qn('w:val'), 'true'); trPr.append(th)
        for row in table.rows:
            trPr = row._tr.get_or_add_trPr()
            if not trPr.xpath('./w:cantSplit'):
                cs = OxmlElement('w:cantSplit'); cs.set(qn('w:val'), 'true'); trPr.append(cs)

    # Remove trailing empty paragraphs.
    nonempty = [i for i,p in enumerate(doc.paragraphs) if p.text.strip()]
    if nonempty:
        last = max(nonempty)
        for p in list(doc.paragraphs[last+1:]):
            p._element.getparent().remove(p._element)

    changes.append(f'equation_numbers={add_equation_numbers(doc)}')
    for cap in ['图4  级联准入前置候选的条件证据支持精度', '图5  最终严格知识的条件证据支持精度']:
        if keep_figure_caption_together(doc, cap):
            changes.append(f'keep_caption={cap}')

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)

    # Replace the three source images with the data-backed round-2 figures.
    replace_media(OUT, {
        'image15.png': FIGDIR / 'fig4_pre_gate_precision_round3.png',
        'image16.png': FIGDIR / 'fig5_final_strict_precision_round3.png',
        'image20.png': FIGDIR / 'fig9_nanchang_event_network_round3.png',
    })

    # Clear legacy Word field instructions that LibreOffice otherwise renders.
    tmp = OUT.with_suffix('.field.tmp.docx')
    with zipfile.ZipFile(OUT, 'r') as zin, zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.endswith('.xml') and b'MACROBUTTON MTPlaceRef' in data:
                data = re.sub(rb'(<w:instrText[^>]*>)[^<]*MACROBUTTON MTPlaceRef[^<]*(</w:instrText>)', rb'\1\2', data)
            zout.writestr(item, data)
    tmp.replace(OUT)
    (BASE / 'deliverables' / 'revision_log_round3.txt').write_text('\n'.join(changes) + f'\nOUTPUT={OUT}', encoding='utf-8')
    print('\n'.join(changes)); print('OUTPUT', OUT)

if __name__ == '__main__':
    main()
