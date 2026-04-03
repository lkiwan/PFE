import re
from pathlib import Path
from typing import Dict, List, Optional
import pdfplumber

class AMMCReportExtractor:
    """
    Extracts financial metrics directly from AMMC PDF reports (Bilan, CPR).
    Utilizes regex and pdfplumber to parse complex tabular financial statements.
    """
    
    METRICS_MAPPING = {
        "total_actif": [r"\btotal\s+actif\b", r"total\s+de\s+l['’]actif"],
        "capitaux_propres_pg": [r"capitaux\s+propres\s*[-–]\s*part\s+du\s+groupe", r"capitaux\s+propres\s+pg", r"total\s+capitaux\s+propres"],
        "dettes_financieres_lt": [r"dette[s]?\s+financi[eè]re[s]?\s+non\s+courante[s]?", r"dette[s]?\s+financi[eè]re[s]?\s+long\s+terme"],
        "dettes_financieres_ct": [r"dette[s]?\s+financi[eè]re[s]?\s+courante[s]?", r"dette[s]?\s+financi[eè]re[s]?\s+court\s+terme", r"concours\s+bancaires"],
        "tresorerie_nette": [r"tr[eé]sorerie\s+nette", r"position\s+de\s+tr[eé]sorerie\s+nette"],
        "creances_clients": [r"cr[eé]ances\s+clients?", r"cr[eé]ances\s+client[eè]le"],
        "chiffre_d_affaires_pnb": [r"chiffre\s+d['’]affaires", r"produit\s+net\s+bancaire", r"\bPNB\b"],
        "resultat_brut_exploitation": [r"r[eé]sultat\s+brut\s+d['’]exploitation", r"rbe\b", r"ebitda"],
        "resultat_net_pg": [r"r[eé]sultat\s+net\s+part\s+du\s+groupe", r"r[eé]sultat\s+net\s+pg", r"rnpg"],
        "cout_du_risque": [r"co[uû]t\s+du\s+risque", r"dotations\s+aux\s+provisions\s+pour\s+cr[eé]ances"],
        "dotations_amortissements": [r"dotations?\s+aux\s+amortissements", r"amortissements\s+et\s+provisions"],
        "flux_tresorerie_operationnel": [r"flux.*?tr[eé]sorerie.*?activit[eé]s?\s+op[eé]rationnelles", r"caf", r"capacit[eé]\s+d['’]autofinancement"],
        "capex": [r"capex", r"d[eé]penses?\s+d['’]investissement", r"investissements?\s+corporels"],
        "nombre_actions_circulation": [r"nombre\s+d['’]actions\s+en\s+circulation", r"nombre\s+total\s+d['’]actions"],
        "dividende_par_action": [r"dividende\s+par\s+action", r"DPA\b"],
    }

    def __init__(self, pdf_path: str):
        self.pdf_path = Path(pdf_path)

    def _parse_number(self, text: str) -> Optional[float]:
        if not text: return None
        clean_text = text.replace(" ", "").replace("\u00a0", "")
        if clean_text.startswith("(") and clean_text.endswith(")"):
            clean_text = "-" + clean_text[1:-1]
        clean_text = clean_text.replace(",", ".")
        clean_text = re.sub(r"[^\d.-]", "", clean_text)
        try:
            return float(clean_text)
        except ValueError:
            return None

    def _find_value_in_line(self, line: str) -> Optional[float]:
        parts = re.split(r'\s{2,}', line.strip())
        candidates = []
        
        if len(parts) < 2:
            p = r"(?<![\d.])(?:\-?\s*)?\d{1,3}(?:[\s\u00a0]\d{3})+(?:,\d+)?(?!\d)"
            matches = re.findall(p, line)
            if matches:
                for m in matches:
                     candidates.append(self._parse_number(m))
            else:
                 p2 = r"(?<![\d.])(?:\-?\s*)?\d+(?:,\d+)?(?!\d)" 
                 matches2 = re.findall(p2, line)
                 for m in matches2:
                     candidates.append(self._parse_number(m))
        else:
            for part in parts:
                val = self._parse_number(part)
                if val is not None:
                    candidates.append(val)
                    
        valid = [x for x in candidates if x is not None]
        if not valid: return None
        return valid[-1] # Return the most recent year (usually the last column in Moroccan PDFs)

    def _find_metric_value(self, full_text: str, patterns: List[str]) -> tuple[Optional[float], Optional[str]]:
        lines = full_text.splitlines()
        regexes = [re.compile(pat, re.IGNORECASE) for pat in patterns]
        
        best_val, best_line, max_numbers_in_line = None, None, 0
        
        for line in lines:
            for r in regexes:
                if r.search(line):
                    if "%" in line: continue
                    formatted_num_pat = r"\d{1,3}(?:[\s\u00a0]\d{3})+(?:,\d+)?"
                    count = len(re.findall(formatted_num_pat, line))
                    val = self._find_value_in_line(line)
                    
                    if val is not None:
                        if count > max_numbers_in_line:
                            max_numbers_in_line = count
                            best_val, best_line = val, line
                        elif count == max_numbers_in_line and best_val is None:
                             best_val, best_line = val, line
                             
        return best_val, best_line

    def extract_all(self) -> Dict[str, float]:
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF not found at {self.pdf_path}")
            
        print(f"📄 Extracting text from {self.pdf_path.name}...")
        full_text = ""
        with pdfplumber.open(self.pdf_path) as pdf:
            for page in pdf.pages:
                extract = page.extract_text(x_tolerance=2, y_tolerance=2)
                if extract: full_text += extract + "\n"
                
        results = {}
        print("🔍 Scanning for financial metrics...")
        for metric, patterns in self.METRICS_MAPPING.items():
            val, _ = self._find_metric_value(full_text, patterns)
            if val is not None:
                results[metric] = val
                print(f"   [+] Found {metric}: {val}")
            else:
                print(f"   [-] Missing {metric}")
                
        return results
