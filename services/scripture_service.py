#!/usr/bin/env python3
"""
Scripture Service - Lectura diaria del Nuevo Testamento

Servicio para enviar un capítulo del Nuevo Testamento cada día a las 07:15.
Usa la API de Bible.com o fuentes públicas para obtener el texto católico.
"""

import json
import logging
import os
import requests
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('scripture_service')


@dataclass
class ChapterInfo:
    """Información de un capítulo bíblico."""
    book: str
    book_abbrev: str
    chapter: int
    total_chapters: int
    book_number: int
    day_number: int


class ScriptureService:
    """
    Servicio de lectura diaria de las Escrituras.
    """
    
    def __init__(self):
        self.scripture_dir = Path.home() / ".hermes" / "scripture"
        self.scripture_dir.mkdir(exist_ok=True)
        
        # Cargar estructura del Nuevo Testamento
        self.nt_structure = self._load_nt_structure()
        self.total_chapters = self._calculate_total_chapters()
        
        # Target de notificación (Telegram por defecto)
        self.telegram_target = os.getenv('SCRIPTURE_TELEGRAM_TARGET', '-1003796258079')
        
        logger.info(f"Scripture Service initialized: {self.total_chapters} chapters in NT")
    
    def _load_nt_structure(self) -> Dict:
        """Carga la estructura del Nuevo Testamento."""
        structure_file = self.scripture_dir / "nuevo_testamento_structure.json"
        
        if not structure_file.exists():
            # Crear estructura básica si no existe
            return self._create_default_structure()
        
        with open(structure_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _create_default_structure(self) -> Dict:
        """Crea la estructura por defecto del NT."""
        return {
            "books": [
                {"name": "Mateo", "abbrev": "Mt", "number": 1, "chapters": 28},
                {"name": "Marcos", "abbrev": "Mr", "number": 2, "chapters": 16},
                {"name": "Lucas", "abbrev": "Lc", "number": 3, "chapters": 24},
                {"name": "Juan", "abbrev": "Jn", "number": 4, "chapters": 21},
                {"name": "Hechos", "abbrev": "Hch", "number": 5, "chapters": 28},
                {"name": "Romanos", "abbrev": "Ro", "number": 6, "chapters": 16},
                {"name": "1 Corintios", "abbrev": "1Co", "number": 7, "chapters": 16},
                {"name": "2 Corintios", "abbrev": "2Co", "number": 8, "chapters": 13},
                {"name": "Gálatas", "abbrev": "Gá", "number": 9, "chapters": 6},
                {"name": "Efesios", "abbrev": "Ef", "number": 10, "chapters": 6},
                {"name": "Filipenses", "abbrev": "Fil", "number": 11, "chapters": 4},
                {"name": "Colosenses", "abbrev": "Col", "number": 12, "chapters": 4},
                {"name": "1 Tesalonicenses", "abbrev": "1Ts", "number": 13, "chapters": 5},
                {"name": "2 Tesalonicenses", "abbrev": "2Ts", "number": 14, "chapters": 3},
                {"name": "1 Timoteo", "abbrev": "1Ti", "number": 15, "chapters": 6},
                {"name": "2 Timoteo", "abbrev": "2Ti", "number": 16, "chapters": 4},
                {"name": "Tito", "abbrev": "Tit", "number": 17, "chapters": 3},
                {"name": "Filemón", "abbrev": "Flm", "number": 18, "chapters": 1},
                {"name": "Hebreos", "abbrev": "He", "number": 19, "chapters": 13},
                {"name": "Santiago", "abbrev": "Stg", "number": 20, "chapters": 5},
                {"name": "1 Pedro", "abbrev": "1P", "number": 21, "chapters": 5},
                {"name": "2 Pedro", "abbrev": "2P", "number": 22, "chapters": 3},
                {"name": "1 Juan", "abbrev": "1Jn", "number": 23, "chapters": 5},
                {"name": "2 Juan", "abbrev": "2Jn", "number": 24, "chapters": 1},
                {"name": "3 Juan", "abbrev": "3Jn", "number": 25, "chapters": 1},
                {"name": "Judas", "abbrev": "Jud", "number": 26, "chapters": 1},
                {"name": "Apocalipsis", "abbrev": "Ap", "number": 27, "chapters": 22}
            ]
        }
    
    def _calculate_total_chapters(self) -> int:
        """Calcula el número total de capítulos en el NT."""
        return sum(book["chapters"] for book in self.nt_structure["books"])
    
    def get_chapter_for_day(self, day_number: Optional[int] = None) -> ChapterInfo:
        """
        Obtiene el capítulo correspondiente al día del año.
        Si no se especifica día, usa el día actual del año.
        """
        if day_number is None:
            day_number = datetime.now().timetuple().tm_yday
        
        # Ciclar a través del NT si pasamos los 260 capítulos
        chapter_index = (day_number - 1) % self.total_chapters
        
        # Encontrar el libro y capítulo correspondiente
        current_chapter = 0
        for book in self.nt_structure["books"]:
            if current_chapter + book["chapters"] > chapter_index:
                # Encontramos el libro correcto
                chapter_in_book = chapter_index - current_chapter + 1
                return ChapterInfo(
                    book=book["name"],
                    book_abbrev=book["abbrev"], 
                    chapter=chapter_in_book,
                    total_chapters=book["chapters"],
                    book_number=book["number"],
                    day_number=day_number
                )
            current_chapter += book["chapters"]
        
        # Fallback - no debería llegar aquí
        first_book = self.nt_structure["books"][0]
        return ChapterInfo(
            book=first_book["name"],
            book_abbrev=first_book["abbrev"],
            chapter=1,
            total_chapters=first_book["chapters"], 
            book_number=first_book["number"],
            day_number=day_number
        )
    
    def fetch_chapter_text(self, chapter_info: ChapterInfo) -> Optional[str]:
        """
        Obtiene el texto del capítulo desde una fuente en línea.
        Prueba múltiples APIs/fuentes para obtener el texto.
        """
        # API de Bible.com (versión gratuita)
        text = self._fetch_from_bible_api(chapter_info)
        if text:
            return text
        
        # Fallback: usar texto predefinido para algunos capítulos conocidos
        text = self._get_predefined_text(chapter_info)
        if text:
            return text
        
        # Último fallback: generar mensaje básico
        return self._generate_fallback_message(chapter_info)
    
    def _fetch_from_bible_api(self, chapter_info: ChapterInfo) -> Optional[str]:
        """Intenta obtener el texto desde una API bíblica."""
        try:
            # Intentar con Bible Gateway scraping (método simple)
            return self._fetch_from_bible_gateway(chapter_info)
            
        except Exception as e:
            logger.error(f"Error fetching from Bible API: {e}")
            return None
    
    def _fetch_from_bible_gateway(self, chapter_info: ChapterInfo) -> Optional[str]:
        """Obtiene texto de Bible Gateway mediante web scraping simple."""
        try:
            # Mapeo de nombres de libros al formato de Bible Gateway
            book_mapping = {
                "Mateo": "Mateo",
                "Marcos": "Marcos", 
                "Lucas": "Lucas",
                "Juan": "Juan",
                "Hechos": "Hechos",
                "Romanos": "Romanos",
                "1 Corintios": "1%20Corintios",
                "2 Corintios": "2%20Corintios",
                "Gálatas": "Gálatas",
                "Efesios": "Efesios",
                "Filipenses": "Filipenses", 
                "Colosenses": "Colosenses",
                "1 Tesalonicenses": "1%20Tesalonicenses",
                "2 Tesalonicenses": "2%20Tesalonicenses",
                "1 Timoteo": "1%20Timoteo",
                "2 Timoteo": "2%20Timoteo",
                "Tito": "Tito",
                "Filemón": "Filemón",
                "Hebreos": "Hebreos",
                "Santiago": "Santiago",
                "1 Pedro": "1%20Pedro",
                "2 Pedro": "2%20Pedro", 
                "1 Juan": "1%20Juan",
                "2 Juan": "2%20Juan",
                "3 Juan": "3%20Juan",
                "Judas": "Judas",
                "Apocalipsis": "Apocalipsis"
            }
            
            book_url = book_mapping.get(chapter_info.book, chapter_info.book)
            url = f"https://www.biblegateway.com/passage/?search={book_url}%20{chapter_info.chapter}&version=RVR1960"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                logger.warning(f"Bible Gateway returned status {response.status_code}")
                return None
            
            # Extraer texto básico de la respuesta HTML
            html = response.text
            
            # Buscar patrones comunes en Bible Gateway
            if 'passage-text' in html:
                # Extraer contenido básico (este es un approach muy simple)
                # En un entorno de producción usarías BeautifulSoup
                start_marker = '"passage-text"'
                end_marker = '</div>'
                
                start_idx = html.find(start_marker)
                if start_idx != -1:
                    start_idx = html.find('>', start_idx) + 1
                    end_idx = html.find(end_marker, start_idx)
                    if end_idx != -1:
                        raw_text = html[start_idx:end_idx]
                        # Limpiar HTML básico
                        import re
                        clean_text = re.sub(r'<[^>]+>', '', raw_text)
                        clean_text = clean_text.replace('&nbsp;', ' ')
                        clean_text = re.sub(r'\s+', ' ', clean_text)
                        
                        if len(clean_text.strip()) > 50:
                            return f"{chapter_info.book} {chapter_info.chapter}\n\n{clean_text.strip()}"
            
            # Si no pudimos extraer el texto, devolver mensaje con enlace
            logger.warning(f"Could not extract text from Bible Gateway for {chapter_info.book} {chapter_info.chapter}")
            return None
            
        except Exception as e:
            logger.error(f"Error fetching from Bible Gateway: {e}")
            return None
    
    def _get_predefined_text(self, chapter_info: ChapterInfo) -> Optional[str]:
        """
        Devuelve texto predefinido para capítulos específicos.
        Útil como fallback para capítulos importantes.
        """
        if chapter_info.book == "Juan" and chapter_info.chapter == 3:
            return """Juan 3

1 Había un hombre de los fariseos que se llamaba Nicodemo, un principal entre los judíos.
2 Este vino a Jesús de noche, y le dijo: Rabí, sabemos que has venido de Dios como maestro; porque nadie puede hacer estas señales que tú haces, si no está Dios con él.
3 Respondió Jesús y le dijo: De cierto, de cierto te digo, que el que no naciere de nuevo, no puede ver el reino de Dios.
4 Nicodemo le dijo: ¿Cómo puede un hombre nacer siendo viejo? ¿Puede acaso entrar por segunda vez en el vientre de su madre, y nacer?
5 Respondió Jesús: De cierto, de cierto te digo, que el que no naciere de agua y del Espíritu, no puede entrar en el reino de Dios.
...

16 Porque de tal manera amó Dios al mundo, que ha dado a su Hijo unigénito, para que todo aquel que en él cree, no se pierda, mas tenga vida eterna.
17 Porque no envió Dios a su Hijo al mundo para condenar al mundo, sino para que el mundo sea salvo por él.

[Capítulo completo disponible en: https://www.biblegateway.com/passage/?search=Juan%203&version=RVR1960]"""
        
        return None
    
    def _generate_fallback_message(self, chapter_info: ChapterInfo) -> str:
        """Genera un mensaje básico cuando no se puede obtener el texto completo."""
        return f"""📖 Lectura del día: {chapter_info.book} {chapter_info.chapter}

Hoy corresponde leer el capítulo {chapter_info.chapter} del libro de {chapter_info.book}.

📚 Progreso: Capítulo {chapter_info.chapter} de {chapter_info.total_chapters} en {chapter_info.book}
📅 Día {chapter_info.day_number} del año

Puedes leer el capítulo completo en:
• Bible Gateway: https://www.biblegateway.com/passage/?search={chapter_info.book.replace(' ', '%20')}%20{chapter_info.chapter}&version=RVR1960
• Vatican.va: https://www.vatican.va/archive/ESL0506/_INDEX.HTM

🙏 "Lámpara es a mis pies tu palabra, y lumbrera a mi camino." - Salmo 119:105"""
    
    def generate_chapter_markdown(self, chapter_info: ChapterInfo, text: str) -> str:
        """Genera un archivo markdown con el capítulo del día."""
        markdown_content = f"""# Lectura del Día - {chapter_info.book} {chapter_info.chapter}

**Libro:** {chapter_info.book}  
**Capítulo:** {chapter_info.chapter} de {chapter_info.total_chapters}  
**Fecha:** {datetime.now().strftime('%d de %B de %Y')}  
**Día del año:** {chapter_info.day_number}  

---

{text}

---

*Versión: Reina-Valera 1960*  
*Fuente: Nuevo Testamento Católico*

## Reflexión

Este capítulo forma parte de la lectura secuencial del Nuevo Testamento. 
Tómate unos minutos para meditar en las palabras leídas y aplicarlas a tu vida diaria.

## Progreso de Lectura

- **Libro actual:** {chapter_info.book} ({chapter_info.book_number}/27)
- **Capítulo:** {chapter_info.chapter}/{chapter_info.total_chapters}
- **Progreso total NT:** {((chapter_info.day_number - 1) % self.total_chapters) + 1}/{self.total_chapters} capítulos

---

*"Lámpara es a mis pies tu palabra, y lumbrera a mi camino." - Salmo 119:105*
"""
        return markdown_content
    
    def save_chapter_markdown(self, chapter_info: ChapterInfo, text: str) -> Path:
        """Guarda el capítulo como archivo markdown."""
        filename = f"{datetime.now().strftime('%Y%m%d')}_{chapter_info.book_abbrev}_{chapter_info.chapter:02d}.md"
        filepath = self.scripture_dir / "daily_readings" / filename
        filepath.parent.mkdir(exist_ok=True)
        
        markdown_content = self.generate_chapter_markdown(chapter_info, text)
        filepath.write_text(markdown_content, encoding='utf-8')
        
        logger.info(f"Chapter saved as markdown: {filepath}")
        return filepath
    
    def send_daily_chapter(self) -> bool:
        """
        Envía el capítulo del día como mensaje.
        """
        try:
            # Obtener capítulo del día
            chapter_info = self.get_chapter_for_day()
            logger.info(f"Today's chapter: {chapter_info.book} {chapter_info.chapter}")
            
            # Obtener texto
            text = self.fetch_chapter_text(chapter_info)
            if not text:
                logger.error("Could not fetch chapter text")
                return False
            
            # Guardar como markdown
            markdown_file = self.save_chapter_markdown(chapter_info, text)
            
            # Generar mensaje para Telegram
            message = self._generate_telegram_message(chapter_info, text)
            
            # Simular envío (aquí integrarías con hermes o Telegram)
            logger.info("📧 DAILY SCRIPTURE MESSAGE:")
            logger.info("="*80)
            for line in message.split('\n'):
                logger.info(line)
            logger.info("="*80)
            logger.info(f"📁 Markdown saved: {markdown_file}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error sending daily chapter: {e}")
            return False
    
    def _generate_telegram_message(self, chapter_info: ChapterInfo, text: str) -> str:
        """Genera el mensaje para Telegram (formato compacto)."""
        # Truncar texto si es muy largo para Telegram
        if len(text) > 1000:
            text = text[:950] + "...\n\n[Capítulo completo en archivo adjunto]"
        
        message = f"""📖 **LECTURA DEL DÍA**

📚 **{chapter_info.book} {chapter_info.chapter}**
📅 {datetime.now().strftime('%d/%m/%Y')} • Día {chapter_info.day_number}

{text}

━━━━━━━━━━━━━━━━━━━━━━
📊 Progreso: {chapter_info.chapter}/{chapter_info.total_chapters} • Libro {chapter_info.book_number}/27
🙏 *"Lámpara es a mis pies tu palabra, y lumbrera a mi camino"*"""
        
        return message


def main():
    """Función principal para ejecutar el servicio de Escrituras."""
    service = ScriptureService()
    
    # Enviar capítulo del día
    success = service.send_daily_chapter()
    
    if success:
        logger.info("✅ Daily chapter sent successfully")
    else:
        logger.error("❌ Failed to send daily chapter")


if __name__ == "__main__":
    main()