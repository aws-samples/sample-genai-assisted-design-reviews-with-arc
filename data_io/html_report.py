"""HTML report generation for resolved policies."""

import json
import base64
import markdown
from pathlib import Path
from models.arc import ResolvedPolicy


def generate_html_report(spec_title: str, spec_file_path: Path,
                         chapters_data: list[tuple[str, list[ResolvedPolicy]]],
                         output_path: Path) -> None:
    """
    Generate an HTML report showing resolved policies with embedded documents.
    
    Parameters
    ----------
    spec_title : Title of the technical specification
    spec_file_path : Path to the technical specification PDF
    chapters_data : List of tuples (chapter_title, policies) organized by chapter
    output_path : Path where the HTML report will be saved
    """
    chapters = {title: policies for title, policies in chapters_data}

    # Encode PDFs as base64 for embedding
    spec_pdf_b64 = base64.b64encode(spec_file_path.read_bytes()).decode('utf-8')

    # Get proposal PDFs (assuming all policies reference the same proposals)
    proposal_pdfs = []
    all_policies = [p for policies in chapters.values() for p in policies]
    if all_policies and all_policies[0].proposal_paths:
        for i, prop_path in enumerate(all_policies[0].proposal_paths):
            proposal_pdfs.append({
                'name': prop_path.name,
                'data': base64.b64encode(prop_path.read_bytes()).decode('utf-8')
            })

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Policy Compliance Report - {spec_title}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; }}
        .container {{ display: flex; height: 100vh; }}
        .sidebar {{ width: 500px; background: white; overflow-y: auto; border-right: 1px solid #ddd; min-width: 200px; max-width: 800px; }}
        .resizer {{ width: 5px; cursor: col-resize; background: #ddd; flex-shrink: 0; }}
        .resizer:hover {{ background: #ff9900; }}
        .content {{ flex: 1; display: flex; flex-direction: column; }}
        .header {{ background: #232f3e; color: white; padding: 20px; }}
        .header h1 {{ font-size: 24px; margin-bottom: 5px; }}
        .header p {{ opacity: 0.8; font-size: 14px; }}
        .documents {{ display: flex; height: calc(100vh - 80px); }}
        .doc-panel {{ flex: 1; display: flex; flex-direction: column; border-right: 1px solid #ddd; }}
        .doc-panel:last-child {{ border-right: none; }}
        .doc-header {{ background: #f8f9fa; padding: 10px 15px; border-bottom: 1px solid #ddd; font-weight: 600; }}
        .doc-viewer {{ flex: 1; background: #525252; }}
        iframe {{ width: 100%; height: 100%; border: none; }}
        .chapter {{ border-bottom: 1px solid #eee; }}
        .chapter-header {{ padding: 15px; background: #f8f9fa; cursor: pointer; font-weight: 600; }}
        .chapter-header:hover {{ background: #e9ecef; }}
        .chapter-content {{ display: none; }}
        .chapter.expanded .chapter-content {{ display: block; }}
        .policy {{ border-bottom: 1px solid #f0f0f0; }}
        .policy-header {{ padding: 12px 15px; cursor: pointer; background: white; }}
        .policy-header:hover {{ background: #f8f9fa; }}
        .policy-name {{ font-weight: 600; color: #232f3e; margin-bottom: 4px; }}
        .policy-desc {{ font-size: 13px; color: #666; }}
        .policy-content {{ display: none; padding: 15px; background: #fafafa; }}
        .policy.expanded .policy-content {{ display: block; }}
        .section {{ margin-bottom: 20px; }}
        .section-title {{ font-weight: 600; color: #232f3e; margin-bottom: 8px; font-size: 14px; }}
        .variable {{ background: white; padding: 10px; margin-bottom: 8px; border-radius: 4px; border-left: 3px solid #ff9900; }}
        .variable-name {{ font-weight: 600; color: #232f3e; }}
        .variable-value {{ color: #0073bb; margin-top: 4px; }}
        .variable-desc {{ font-size: 12px; color: #666; margin-top: 4px; }}
        .rule {{ background: white; padding: 10px; margin-bottom: 8px; border-radius: 4px; }}
        .rule-id {{ font-weight: 600; color: #666; font-size: 12px; }}
        .rule-expr {{ font-family: 'Courier New', monospace; font-size: 13px; margin-top: 4px; color: #232f3e; }}
        .comments {{ background: #fff3cd; padding: 12px; border-radius: 4px; border-left: 3px solid #ffc107; }}
        .comments-title {{ font-weight: 600; color: #856404; margin-bottom: 8px; }}
        .comments-text {{ color: #856404; font-size: 13px; white-space: pre-wrap; }}
        .comments-text ul, .comments-text ol {{ margin: 8px 0; padding-left: 20px; }}
        .finding {{ padding: 12px; border-radius: 4px; margin-bottom: 8px; }}
        .finding-success {{ background: #d4edda; border-left: 3px solid #28a745; color: #155724; }}
        .finding-warning {{ background: #fff3cd; border-left: 3px solid #ffc107; color: #856404; }}
        .finding-error {{ background: #f8d7da; border-left: 3px solid #dc3545; color: #721c24; }}
        .finding-text {{ font-size: 13px; }}
        .finding-text strong {{ font-weight: 600; }}
        .finding-text ul {{ margin: 8px 0; padding-left: 20px; list-style-type: disc; }}
        .finding-text ol {{ margin: 8px 0; padding-left: 20px; }}
        .finding-text li {{ margin: 4px 0; }}
        .tab-container {{ display: flex; background: #f8f9fa; border-bottom: 1px solid #ddd; }}
        .tab {{ padding: 10px 20px; cursor: pointer; border-right: 1px solid #ddd; }}
        .tab.active {{ background: white; font-weight: 600; }}
        .tab:hover {{ background: #e9ecef; }}
        .tab.active:hover {{ background: white; }}
        table {{ border-collapse: collapse; width: 100%; margin: 10px 0; background: white; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background: #f8f9fa; font-weight: 600; color: #232f3e; }}
        tr:hover {{ background: #f8f9fa; }}
        .tooltip {{ position: relative; cursor: help; border-bottom: 1px dotted #666; }}
        .tooltip .tooltiptext {{ visibility: hidden; width: 300px; background: #232f3e; color: white; text-align: left; border-radius: 4px; padding: 8px; position: absolute; z-index: 1; bottom: 125%; left: 50%; margin-left: -150px; opacity: 0; transition: opacity 0.3s; font-size: 12px; }}
        .tooltip:hover .tooltiptext {{ visibility: visible; opacity: 1; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="sidebar" id="sidebar">
            <div class="header">
                <h1>{spec_title}</h1>
                <p>Policy Compliance Report</p>
            </div>
"""

    # Generate chapter/policy navigation
    for chapter_idx, (chapter_name, policies) in enumerate(chapters.items()):
        html += f"""
            <div class="chapter" id="chapter-{chapter_idx}">
                <div class="chapter-header" onclick="toggleChapter({chapter_idx})">
                    📁 {chapter_name[:60]}
                </div>
                <div class="chapter-content">
"""
        for policy_idx, policy in enumerate(policies):
            # Escape description for HTML attribute
            escaped_desc = policy.description.replace('"', '&quot;').replace("'", '&#39;')
            html += f"""
                    <div class="policy" id="policy-{chapter_idx}-{policy_idx}">
                        <div class="policy-header" onclick="togglePolicy({chapter_idx}, {policy_idx})">
                            <div class="policy-name">{policy.name}</div>
                            <div class="policy-desc">{escaped_desc[:200]}</div>
                        </div>
                        <div class="policy-content">
"""
            # Findings section (first)
            if policy.findings:
                html += """
                            <div class="section">
"""
                for finding in policy.findings:
                    severity_class = f"finding-{finding.severity}"
                    formatted_insight = markdown.markdown(finding.insight)
                    html += f"""
                                <div class="finding {severity_class}">
                                    <div class="finding-text">{formatted_insight}</div>
                                </div>
"""
                html += """
                            </div>
"""
            
            # Detailed findings section (collapsible)
            if policy.ar_assessment:
                findings_json = json.dumps(policy.ar_assessment, indent=2)
                html += f"""
                            <div class="section">
                                <details style="background: white; padding: 12px; border-radius: 4px; border-left: 3px solid #0073bb;">
                                    <summary style="cursor: pointer; font-weight: 600; color: #232f3e;">🔍 Detailed Findings</summary>
                                    <pre style="margin-top: 12px; background: #f8f9fa; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px;">{findings_json}</pre>
                                </details>
                            </div>
"""

            # Variables section
            if policy.variables and len([v for v in policy.variables if v.value]) > 0:
                html += """
                            <div class="section">
                                <div class="section-title">📊 Variables</div>
"""
                for var in policy.variables:
                    if var.value:
                        html += f"""
                                    <div class="variable">
                                        <div class="variable-name">{var.name}</div>
                                        <div class="variable-value">Value: {var.value}</div>
                                        <div class="variable-desc">{var.description}</div>
                                    </div>
    """
                html += """
                            </div>
"""

                # Rules section
                if policy.rules:
                    html += """
                                <div class="section">
                                    <div class="section-title">📋 Rules</div>
    """
                    for rule in policy.rules:
                        html += f"""
                                    <div class="rule">
                                        <div class="rule-id">Rule ID: {rule.id}</div>
                                        <div class="rule-expr">{rule.alternate_expression}</div>
                                    </div>
    """
                    html += """
                                </div>
    """

            html += """
                        </div>
                    </div>
"""

        html += """
                </div>
            </div>
"""

    html += """
        </div>
        <div class="resizer" id="resizer"></div>
        <div class="content">
            <div class="tab-container">
"""

    for i, prop in enumerate(proposal_pdfs):
        active = " active" if i == 0 else ""
        html += f"""
                <div class="tab{active}" onclick="switchTab({i})">{prop['name']}</div>
"""

    html += f"""
                <div class="tab" onclick="switchTab({len(proposal_pdfs)})">Technical Specification</div>
            </div>
            <div class="documents">
"""

    # Proposal viewers (first)
    for i, prop in enumerate(proposal_pdfs):
        display = "flex" if i == 0 else "none"
        html += f"""
                <div class="doc-panel" id="doc-{i}" style="display: {display};">
                    <iframe src="data:application/pdf;base64,{prop['data']}"></iframe>
                </div>
"""

    # Technical spec viewer (last)
    html += f"""
                <div class="doc-panel" id="doc-{len(proposal_pdfs)}" style="display: none;">
                    <iframe src="data:application/pdf;base64,{spec_pdf_b64}"></iframe>
                </div>
"""

    html += """
            </div>
        </div>
    </div>
    <script>
        function toggleChapter(idx) {
            const chapter = document.getElementById(`chapter-${idx}`);
            chapter.classList.toggle('expanded');
        }
        
        function togglePolicy(chapterIdx, policyIdx) {
            const policy = document.getElementById(`policy-${chapterIdx}-${policyIdx}`);
            policy.classList.toggle('expanded');
        }
        
        function switchTab(idx) {
            document.querySelectorAll('.tab').forEach((tab, i) => {
                tab.classList.toggle('active', i === idx);
            });
            document.querySelectorAll('.doc-panel').forEach((panel, i) => {
                panel.style.display = i === idx ? 'flex' : 'none';
            });
        }
        
        const resizer = document.getElementById('resizer');
        const sidebar = document.getElementById('sidebar');
        let isResizing = false;
        
        resizer.addEventListener('mousedown', (e) => {
            isResizing = true;
            document.body.style.cursor = 'col-resize';
        });
        
        document.addEventListener('mousemove', (e) => {
            if (!isResizing) return;
            const newWidth = e.clientX;
            if (newWidth >= 200 && newWidth <= 800) {
                sidebar.style.width = newWidth + 'px';
            }
        });
        
        document.addEventListener('mouseup', () => {
            isResizing = false;
            document.body.style.cursor = 'default';
        });
    </script>
</body>
</html>
"""

    output_path.write_text(html)
