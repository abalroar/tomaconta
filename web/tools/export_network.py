#!/usr/bin/env python3
"""BCB bank branches aggregated by municipality, with official IBGE geometry.

No branch is geocoded. One interior representative point is calculated from each
municipal polygon. The map's identity remains CNPJ-base, separately from IF.data.
Requires requests and Shapely==2.1.2; source caches are outside the public assets.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlencode

import requests
from shapely.geometry import Point, shape

ROOT = Path(__file__).resolve().parents[2]
AGENCIES_URL = "https://olinda.bcb.gov.br/olinda/servico/Informes_Agencias/versao/v1/odata/Agencias"
MALHAS_URL = "https://servicodados.ibge.gov.br/api/v4/malhas/paises/BR"
LOCALITIES_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
GEOGRAPHY_BASELINE = Path(__file__).resolve().parent / "data/bank-network-geography"
RETAIL_SEGMENTS = frozenset(("Banco Múltiplo", "Banco Comercial", "Caixa Econômica Federal"))


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def fetch_json(url, path, *, refresh=False):
    metadata_path = path.with_suffix(path.suffix + ".source.json")
    if not refresh and path.exists() and metadata_path.exists():
        data = path.read_bytes()
        metadata = json.loads(metadata_path.read_text())
        if metadata["url"] != url or metadata["sha256"] != sha(data):
            raise ValueError(f"Cache de fonte inconsistente: {path.name}")
        return json.loads(data), metadata
    response = requests.get(url, timeout=(15, 60))
    response.raise_for_status()  # 401/403/429 stop collection; no alternate host.
    value = response.json()
    metadata = {"url": url, "sha256": sha(response.content), "bytes": len(response.content), "collectedAt": now()}
    write(path, response.content)
    write(metadata_path, encode(metadata))
    return value, metadata


def geography_json(url, path, *, refresh=False, baseline=GEOGRAPHY_BASELINE):
    """Use the reviewed IBGE reference independently of the BCB refresh cycle.

    The original collection timestamp and hash stay unchanged. An explicit
    geography refresh consults IBGE and still fails closed on HTTP errors.
    """
    metadata_path = path.with_suffix(path.suffix + ".source.json")
    if not refresh and path.exists() != metadata_path.exists():
        raise ValueError(f"Referência geográfica incompleta: {path.name}")
    if not refresh and not path.exists() and not metadata_path.exists():
        archived = baseline / (path.name + ".gz")
        provenance = baseline / metadata_path.name
        if not archived.is_file() or not provenance.is_file():
            raise ValueError(f"Referência geográfica versionada ausente: {path.name}")
        data = gzip.decompress(archived.read_bytes())
        metadata = json.loads(provenance.read_text())
        if metadata.get("url") != url or metadata.get("sha256") != sha(data) or metadata.get("bytes") != len(data):
            raise ValueError(f"Referência geográfica inconsistente: {path.name}")
        json.loads(data)
        write(path, data)
        write(metadata_path, encode(metadata))
    return fetch_json(url, path, refresh=refresh)


def collect_agencies(source_dir, *, raw=None, evidence=None, refresh=False):
    if raw is not None:
        data = raw.read_bytes()
        if evidence is None:
            raise ValueError("A reutilização do levantamento exige --agencies-evidence")
        audit = json.loads(evidence.read_text())
        if not audit.get("complete") or audit.get("failure") or audit["rawSha256"] != sha(data):
            raise ValueError("Levantamento de agências incompleto ou SHA-256 divergente")
        rows = json.loads(data)
        if audit["totalRecords"] != len(rows) or sum(page["rows"] for page in audit["pages"]) != len(rows):
            raise ValueError("Paginação do levantamento não fecha com o bruto")
        return rows, {"url": AGENCIES_URL, "sha256": sha(data), "bytes": len(data),
            "collectedAt": audit["collectedAt"], "pages": audit["pages"],
            "pageSize": audit["pageSize"], "orderBy": "CnpjBase,CnpjSequencial,CnpjDv",
            "reuseEvidenceSha256": sha(evidence.read_bytes())}
    cached = source_dir / "agencies.json"
    cached_metadata = source_dir / "agencies.source.json"
    if not refresh and cached.exists() and cached_metadata.exists():
        data = cached.read_bytes()
        metadata = json.loads(cached_metadata.read_text())
        if sha(data) != metadata["sha256"]:
            raise ValueError("Cache de agências inconsistente")
        return json.loads(data), metadata
    rows, pages, size = [], [], 1000
    for skip in range(0, 1_000_000, size):
        query = urlencode({"$format": "json", "$orderby": "CnpjBase,CnpjSequencial,CnpjDv", "$top": size, "$skip": skip})
        payload, metadata = fetch_json(AGENCIES_URL + "?" + query, source_dir / f"agencies-page-{skip:06d}.json", refresh=refresh)
        page = payload.get("value")
        if not isinstance(page, list):
            raise ValueError("Resposta de paginação BCB inválida")
        pages.append({"skip": skip, "rows": len(page), "sha256": metadata["sha256"]})
        rows.extend(page)
        if len(page) < size:
            break
    else:
        raise ValueError("Paginação BCB sem página final")
    data = encode(rows)
    metadata = {"url": AGENCIES_URL, "sha256": sha(data), "bytes": len(data), "collectedAt": now(),
                "pages": pages, "pageSize": size, "orderBy": "CnpjBase,CnpjSequencial,CnpjDv"}
    write(cached, data)
    write(cached_metadata, encode(metadata))
    return rows, metadata


def municipality_code(raw, official_ids):
    code = str(raw).strip()
    if re.fullmatch(r"\d{7}", code) and code in official_ids:
        return code, "exact-7-digit"
    if re.fullmatch(r"\d{6}", code):
        matches = [item for item in official_ids if item[:-1] == code]
        if len(matches) == 1:
            return matches[0], "unique-6-digit-prefix"
    return None, "unmatched-or-ambiguous"


def uf_of(locality):
    if locality.get("microrregiao"):
        return locality["microrregiao"]["mesorregiao"]["UF"]
    return locality["regiao-imediata"]["regiao-intermediaria"]["UF"]


def membership_period(root, requested=None, *, catalog_dir=None):
    """Use the real candidate catalog's competence, never the execution date."""
    directory = Path(catalog_dir) if catalog_dir is not None else root / "web/public/data"
    catalog = json.loads((directory / "institutions.json").read_text())
    match = re.fullmatch(r"(\d{4})-Q([1-4])", str(catalog.get("latestPeriod", "")))
    if not match:
        raise ValueError("Catálogo candidato sem última competência trimestral válida")
    latest = f"{match[1]}{int(match[2]) * 3:02d}"
    if requested is not None:
        value = str(requested).replace("-", "")
        if not re.fullmatch(r"\d{4}(03|06|09|12)", value) or value != latest:
            raise ValueError("--period deve corresponder à última competência real do catálogo candidato")
    return latest


def official_links(root, source_dir, period, cnpj_bases, *, refresh=False, catalog_dir=None):
    """Resolve official membership for each requested CNPJ-base, with no names.

    info.lid=15 describes 'Código do Conglomerado Prudencial'. c33 is the
    individual identifier used by the original IF.data reader. No name matching.
    """
    base = "https://www3.bcb.gov.br/ifdata/rest"
    reports, reports_source = fetch_json(base + "/relatorios2025a2030", source_dir / "ifdata-reports.json", refresh=refresh)
    selected = [item for item in reports if str(item.get("dt")) == period]
    if len(selected) != 1:
        raise ValueError("Competência do cadastro IF.data não publicada")
    files = {Path(item["f"]).name: item["f"] for item in selected[0]["files"]}
    sources, payloads = {"reports": reports_source}, {}
    for kind, name in (("individual", f"cadastro{period}_1006.json"), ("info", f"info{period}.json")):
        url = base + "/arquivos?" + urlencode({"nomeArquivo": files[name]})
        payloads[kind], sources[kind] = fetch_json(url, source_dir / name, refresh=refresh)
    if not any(item.get("td") == 1 and item.get("lid") == 15 and item.get("d") == "Código do Conglomerado Prudencial" for item in payloads["info"]):
        raise ValueError("Sem descrição oficial do campo prudencial c15")
    directory = Path(catalog_dir) if catalog_dir is not None else root / "web/public/data"
    crosswalk_bytes = (directory / "statements/crosswalk.json").read_bytes()
    catalog_bytes = (directory / "institutions.json").read_bytes()
    crosswalk, catalog = json.loads(crosswalk_bytes), json.loads(catalog_bytes)
    sources["analysisCatalog"] = {"path": "institutions.json", "sha256": sha(catalog_bytes)}
    sources["analysisCrosswalk"] = {"path": "statements/crosswalk.json", "sha256": sha(crosswalk_bytes)}
    analysis = {bank["id"]: bank for bank in catalog["institutions"]}
    result, statuses = {}, {}
    for cnpj in sorted(cnpj_bases):
        matches = [item for item in payloads["individual"] if item.get("c33") == cnpj and str(item.get("c1")) == period]
        if len(matches) != 1:
            statuses[cnpj] = "individual-not-found" if not matches else "ambiguous-individual"
            continue
        code = matches[0].get("c15")
        if not isinstance(code, str) or not re.fullmatch(r"C\d{7}", code):
            statuses[cnpj] = "no-prudential-membership"
            continue
        statement = "prudential-" + code
        linked = [(ident, link) for ident, link in crosswalk["links"].items()
                  if link["statementId"] == statement and link["code"] == code and link["scope"] == "prudential"]
        if len(linked) != 1 or analysis.get(linked[0][0], {}).get("perimeter") != "Prudencial":
            statuses[cnpj] = "ambiguous-crosswalk" if len(linked) > 1 else "no-compatible-analysis"
            continue
        statuses[cnpj] = "linked"
        result[cnpj] = {"analysisId": linked[0][0], "statementId": statement, "scope": "prudential", "code": code,
            "analysisName": analysis[linked[0][0]]["name"],
            "effectivePeriod": period, "relationship": "integrante do conglomerado prudencial",
            "crosswalkEffectivePeriod": linked[0][1]["effectivePeriod"],
            "source": "BCB / IF.data · cadastro individual", "sourceSha256": sources["individual"]["sha256"],
            "method": "CNPJ-base = c33; c15 = código prudencial; crosswalk exato e único"}
    return result, statuses, sources


def export(root, output, source_dir, *, agencies=None, evidence=None, refresh=False, refresh_geography=False, link_period=None, catalog_dir=None):
    link_period = membership_period(root, link_period, catalog_dir=catalog_dir)
    rows, agency_source = collect_agencies(source_dir, raw=agencies, evidence=evidence, refresh=refresh)
    full_ids = [(str(r["CnpjBase"]), str(r["CnpjSequencial"]), str(r["CnpjDv"])) for r in rows]
    if len(full_ids) != len(set(full_ids)) or full_ids != sorted(full_ids):
        raise ValueError("Duplicidade ou ordem inconsistente de CNPJ completo")
    if any(not (re.fullmatch(r"\d{8}", a) and re.fullmatch(r"\d{4}", b) and re.fullmatch(r"\d{2}", c)) for a, b, c in full_ids):
        raise ValueError("CNPJ de agência inválido")
    positions = {r["Posicao"] for r in rows}
    if len(positions) != 1:
        raise ValueError("Posições de agências misturadas")
    position = datetime.strptime(next(iter(positions)), "%d/%m/%Y").date().isoformat()
    localities, locality_source = geography_json(LOCALITIES_URL, source_dir / "localities.json", refresh=refresh_geography)
    query = {"qualidade": "minima", "formato": "application/vnd.geo+json"}
    municipalities_geo, municipalities_source = geography_json(MALHAS_URL + "?" + urlencode({"intrarregiao": "municipio", **query}), source_dir / "municipalities.geojson", refresh=refresh_geography)
    ufs_geo, ufs_source = geography_json(MALHAS_URL + "?" + urlencode({"intrarregiao": "UF", **query}), source_dir / "ufs.geojson", refresh=refresh_geography)
    local = {str(item["id"]): item for item in localities}
    geometries = {str(feature["properties"]["codarea"]): feature["geometry"] for feature in municipalities_geo["features"]}
    if len(local) != len(localities) or set(local) != set(geometries):
        raise ValueError("Localidades e malha municipal IBGE não fecham")
    selected = [row for row in rows if row["Segmento"] in RETAIL_SEGMENTS]
    banks, totals, mappings, missing = {}, defaultdict(Counter), Counter(), Counter()
    for row in selected:
        cnpj = row["CnpjBase"]
        item = banks.setdefault(cnpj, {"names": set(), "segments": set(), "count": 0, "municipalities": set(), "ufCounts": Counter()})
        item["names"].add(row["NomeIf"])
        item["segments"].add(row["Segmento"])
        item["count"] += 1
        item["municipalities"].add(row["MunicipioIbge"])
        item["ufCounts"][row["UF"]] += 1
        code, method = municipality_code(row["MunicipioIbge"], local)
        mappings[method] += 1
        if code is None:
            missing[(str(row["MunicipioIbge"]), row["Municipio"], row["UF"])] += 1
            continue
        if uf_of(local[code])["sigla"] != row["UF"]:
            raise ValueError(f"UF BCB/IBGE divergente: {code}")
        totals[code][cnpj] += 1
    municipality_rows, invalid_geometry = [], []
    for code, locality in sorted(local.items()):
        geometry = shape(geometries[code])
        coordinates = {"lon": None, "lat": None}
        if geometry.is_valid and not geometry.is_empty:
            point = geometry.representative_point()
            rounded = Point(round(point.x, 6), round(point.y, 6))
            if not geometry.covers(rounded):
                raise ValueError(f"Ponto arredondado fora do município: {code}")
            coordinates = {"lon": rounded.x, "lat": rounded.y}
        else:
            invalid_geometry.append(code)
        counts = dict(sorted(totals[code].items()))
        municipality_rows.append({"ibge": code, "name": locality["nome"], "uf": uf_of(locality)["sigla"],
            **coordinates, "total": sum(counts.values()), "bankCount": len(counts), "banks": counts})
    unavailable_points = sum(m["total"] for m in municipality_rows if m["lon"] is None or m["lat"] is None)
    if missing or unavailable_points:
        raise ValueError("Há agências sem município/ponto oficial válido; publicação anterior preservada")
    links, link_statuses, link_sources = official_links(root, source_dir, link_period, banks, refresh=refresh, catalog_dir=catalog_dir)
    bank_rows = []
    for cnpj, item in sorted(banks.items(), key=lambda pair: (-pair[1]["count"], pair[0])):
        if len(item["names"]) != 1 or len(item["segments"]) != 1:
            raise ValueError(f"Identidade CNPJ-base com nome/segmento ambíguo: {cnpj}")
        bank_rows.append({"idCnpjBase": cnpj, "name": next(iter(item["names"])), "segment": next(iter(item["segments"])),
            "count": item["count"], "municipalities": len(item["municipalities"]),
            "ufCounts": dict(sorted(item["ufCounts"].items())), "analysisLink": links.get(cnpj),
            "analysisLinkStatus": link_statuses[cnpj]})
    states = {str(uf_of(item)["id"]): uf_of(item) for item in local.values()}
    features = []
    for feature in sorted(ufs_geo["features"], key=lambda feature: str(feature["properties"]["codarea"])):
        code = str(feature["properties"]["codarea"])
        features.append({**feature, "id": code, "properties": {**feature["properties"], "uf": states[code]["sigla"], "name": states[code]["nome"]}})
    if len(features) != 27 or {f["id"] for f in features} != set(states):
        raise ValueError("Malha estadual IBGE incompleta")
    geo_bytes = encode({"type": "FeatureCollection", "features": features})
    mapped = sum(m["total"] for m in municipality_rows)
    unmapped = sum(missing.values())
    if sum(b["count"] for b in bank_rows) != len(selected) or mapped + unmapped != len(selected):
        raise ValueError("Agregações municipais e bancárias não fecham")
    value = {"schemaVersion": 1, "position": position, "generatedAt": now(), "unit": "agências",
        "perimeter": "CNPJ-base da instituição individual no cadastro de agências",
        "segments": sorted(RETAIL_SEGMENTS), "banks": bank_rows, "municipalities": municipality_rows,
        "geometry": {"path": "data/bank-network-ufs.geojson", "sha256": sha(geo_bytes), "bytes": len(geo_bytes)},
        "sources": {"agencies": {**agency_source, "name": "Banco Central do Brasil · Informes Agências", "license": "ODbL-1.0", "licenseSource": "https://dadosabertos.bcb.gov.br/dataset/agencias"},
            "localities": {**locality_source, "name": "IBGE · Localidades"},
            "municipalityGeometry": {**municipalities_source, "name": "IBGE · malhas municipais simplificadas v4", "license": "CC-BY-4.0"},
            "stateGeometry": {**ufs_source, "name": "IBGE · malhas estaduais simplificadas v4", "license": "CC-BY-4.0"},
            "ifdataMembership": {"period": link_period, "sources": link_sources}},
        "methods": {"point": "Ponto interno representativo do polígono municipal oficial IBGE; Shapely 2.1.2 representative_point, arredondado a 6 casas e validado dentro do polígono. Não representa endereço de agência.",
            "municipalityCode": "Código IBGE de 7 dígitos exato; código de 6 dígitos só quando o prefixo identifica uma única localidade oficial.",
            "zero": "total=0 indica ausência de registro no recorte dos três segmentos na posição do cadastro; não inclui postos, caixas eletrônicos ou atendimento digital.",
            "analysisLink": "Cada CNPJ individual é consultado pelo c33 e código prudencial c15 do cadastro oficial IF.data; só há link quando o crosswalk tem uma única análise compatível. Sem associação por nome ou escolha entre aliases. O mapa não agrega entidades do grupo. Posições cadastrais e perímetros diferentes são preservados.",
            "attribution": "Agências: Banco Central do Brasil, ODbL. Cartografia: IBGE, CC BY 4.0. Agregação e pontos representativos: Toma Conta."},
        "checks": {"sourceRecords": len(rows), "sourceCnpjBases": len({r["CnpjBase"] for r in rows}), "duplicateFullCnpj": 0,
            "selectedRecords": len(selected), "bankCount": len(bank_rows), "territoryMunicipalities": len(municipality_rows),
            "municipalitiesWithAgencies": sum(m["total"] > 0 for m in municipality_rows),
            "municipalitiesWithoutAgencies": sum(m["total"] == 0 for m in municipality_rows),
            "municipalitiesSingleBank": sum(m["bankCount"] == 1 for m in municipality_rows),
            "mappedAgencies": mapped, "unmappedAgencies": unmapped, "unavailablePointAgencies": unavailable_points,
            "invalidGeometryMunicipalities": invalid_geometry, "codeMappings": dict(mappings),
            "fiveLargestAgencies": sum(b["count"] for b in bank_rows[:5]),
            "fiveLargestSharePct": round(sum(b["count"] for b in bank_rows[:5]) / len(selected) * 100, 8),
            "analysisLinks": sum(b["analysisLink"] is not None for b in bank_rows),
            "analysisLinkStatuses": dict(Counter(b["analysisLinkStatus"] for b in bank_rows)), "reconciled": True},
        "unmappedMunicipalities": [{"bcbCode": c, "name": n, "uf": u, "count": count} for (c, n, u), count in sorted(missing.items())]}
    write(output / "bank-network-ufs.geojson", geo_bytes)
    write(output / "bank-network.json", encode(value))
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "web/public/data")
    parser.add_argument("--source-dir", type=Path, default=ROOT / "data/cache/bank_network")
    parser.add_argument("--catalog-dir", type=Path, help="Catálogo institutions.json e statements/crosswalk.json do candidato (padrão: ROOT/web/public/data)")
    parser.add_argument("--agencies", type=Path)
    parser.add_argument("--agencies-evidence", type=Path)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--refresh-geography", action="store_true", help="Reconsultar localidades e malhas IBGE; independente da atualização BCB")
    parser.add_argument("--period", "--link-period", dest="link_period", help="Última competência do catálogo candidato (YYYYMM ou YYYY-MM); derivada do catálogo quando omitida")
    args = parser.parse_args()
    result = export(args.root, args.output, args.source_dir, agencies=args.agencies,
                    evidence=args.agencies_evidence, refresh=args.refresh, refresh_geography=args.refresh_geography, link_period=args.link_period, catalog_dir=args.catalog_dir)
    print(json.dumps({"position": result["position"], **result["checks"]}, ensure_ascii=False))
