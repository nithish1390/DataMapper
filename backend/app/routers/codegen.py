import io
import re
import zipfile

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.models.schemas import (
    CodegenResponse, FormulaCheckRequest, FullValidationRequest, FullValidationResponse, MappingAnalysis, FormulaCheckResponse, MappingLink, MappingWorkspace,
    SnippetRequest, SnippetResponse, ValidationResponse, ValidationIssue,
)
from app.services.links import analyse, collect_links
from app.services.validation import validate_full
from app.services.transform_dsl import check_formula
from app.services.xslt_gen import formula_xpath, generate_xslt_snippet
from app.services import codegen
from app.services.mapping_logic import validate_mappings
from app.services.parsers import flatten

router = APIRouter(prefix="/api/codegen", tags=["codegen"])


@router.post("/preview", response_model=CodegenResponse)
def preview(ws: MappingWorkspace) -> CodegenResponse:
    mapper_java, custom_funcs = codegen.generate_mapstruct_mapper(ws)
    xslt = codegen.generate_xslt(ws)
    custom_functions_java = (
        codegen.generate_custom_functions_class(ws.project.package, custom_funcs)
        if custom_funcs else None
    )
    return CodegenResponse(processor_java=mapper_java, xslt=xslt, custom_functions_java=custom_functions_java)


@router.post("/snippet", response_model=SnippetResponse)
def snippet(req: SnippetRequest) -> SnippetResponse:
    """XSLT for one target node — shown live in the centre panel."""
    return SnippetResponse(xslt=generate_xslt_snippet(req.workspace, req.target, req.scope))


@router.post("/links", response_model=list[MappingLink])
def links(ws: MappingWorkspace) -> list[MappingLink]:
    """Resolved source -> target links (for the mapping lines and 'used' markers)."""
    return collect_links(ws)


@router.post("/validate-full", response_model=FullValidationResponse)
def validate_full_route(req: FullValidationRequest) -> FullValidationResponse:
    """Validate screen: coverage, per-row problems and (with a sample) XSD validation of the output."""
    return validate_full(req)


@router.post("/analysis", response_model=MappingAnalysis)
def analysis(ws: MappingWorkspace) -> MappingAnalysis:
    """Links for the mapping lines + per-row problems (shown red in the target tree)."""
    links_, problems = analyse(ws)
    return MappingAnalysis(links=links_, problems=problems)


@router.post("/check-formula", response_model=FormulaCheckResponse)
def check(req: FormulaCheckRequest) -> FormulaCheckResponse:
    """Mapping Builder: syntax check + the XPath it compiles to in its context."""
    error = check_formula(req.text)
    if error:
        return FormulaCheckResponse(ok=False, error=error)
    xpath, context = formula_xpath(req.workspace, req.text, req.target, req.outer)
    return FormulaCheckResponse(ok=True, xpath=xpath, context=context)


@router.post("/validate", response_model=ValidationResponse)
def validate(ws: MappingWorkspace) -> ValidationResponse:
    target_leaves = [n for n in flatten(ws.target.fields) if not n.children]
    unmapped_mandatory, unmapped_optional, issues = validate_mappings(
        target_leaves, ws.target.mandatory_overrides, ws.mappings)
    return ValidationResponse(
        mapped_count=len(target_leaves) - len(unmapped_mandatory) - len(unmapped_optional),
        total_count=len(target_leaves),
        unmapped_mandatory=unmapped_mandatory,
        unmapped_optional=unmapped_optional,
        issues=issues,
    )


@router.post("/project")
def download_project(ws: MappingWorkspace) -> StreamingResponse:
    pkg_path = ws.project.package.replace(".", "/")
    mapper_java, custom_funcs = codegen.generate_mapstruct_mapper(ws)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("pom.xml", codegen.generate_pom(ws))
        zf.writestr("README.md", codegen.generate_readme(ws, mapper_java))
        zf.writestr("src/main/resources/application.yml", codegen.generate_yml(ws))
        zf.writestr(f"src/main/java/{pkg_path}/{codegen.pascal_case(ws.project.artifact)}Application.java",
                    codegen.generate_application_java(ws.project.package, ws.project.artifact))

        for i, s in enumerate(ws.sources):
            if s.type == "xsd":
                xsd_pkg = f"{ws.project.package}.model.xsd{i + 1}"
                files = codegen.xsd_tree_to_java_classes(s.fields, codegen.source_class_name(i), xsd_pkg)
                for fname, content in files.items():
                    zf.writestr(f"src/main/java/{pkg_path}/model/xsd{i + 1}/{fname}", content)
            else:
                zf.writestr(f"src/main/java/{pkg_path}/model/{codegen.source_class_name(i)}.java",
                            codegen.generate_model_class(codegen.source_class_name(i), s.fields,
                                                          ws.project.package, ws.project.dep_lombok))

        if ws.target.type == "xsd":
            xsd_pkg = f"{ws.project.package}.model.xsdtarget"
            files = codegen.xsd_tree_to_java_classes(ws.target.fields, "TargetModel", xsd_pkg)
            for fname, content in files.items():
                zf.writestr(f"src/main/java/{pkg_path}/model/xsdtarget/{fname}", content)
        else:
            zf.writestr(f"src/main/java/{pkg_path}/model/TargetModel.java",
                        codegen.generate_model_class("TargetModel", ws.target.fields,
                                                      ws.project.package, ws.project.dep_lombok))

        zf.writestr(f"src/main/java/{pkg_path}/model/MappingRequest.java", codegen.generate_mapping_request(ws))
        zf.writestr(f"src/main/java/{pkg_path}/mapper/FieldMapperProcessor.java", mapper_java)
        if ws.project.dep_camel:
            zf.writestr(f"src/main/java/{pkg_path}/mapper/CamelMappingProcessor.java",
                        codegen.generate_camel_processor_wrapper(ws))
        if custom_funcs:
            zf.writestr(f"src/main/java/{pkg_path}/mapper/CustomFunctions.java",
                        codegen.generate_custom_functions_class(ws.project.package, custom_funcs))
        zf.writestr(f"src/main/java/{pkg_path}/controller/MappingController.java", codegen.generate_controller(ws))
        zf.writestr("src/main/resources/mapping.xsl", codegen.generate_xslt(ws))
        for cs in ws.custom_sources:
            pkg = re.search(r"^\s*package\s+([\w.]+)\s*;", cs.content, re.M)
            folder = pkg.group(1).replace(".", "/") + "/" if pkg else ""
            zf.writestr(f"src/main/java/{folder}{cs.file_name}", cs.content)
        if ws.custom_jars:
            zf.writestr("lib/README.md", "Copy these custom-function jars here and install them into your Maven repo:\n\n"
                        + "\n".join(f"- {j}" for j in ws.custom_jars) + "\n")

    buf.seek(0)
    filename = f"{ws.project.artifact}.zip"
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
