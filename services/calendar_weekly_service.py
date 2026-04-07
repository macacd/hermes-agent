#!/usr/bin/env python3
"""
Calendar Weekly Service - Envío automático de eventos semanales
Envía diariamente (domingo-jueves, 20:00) los eventos restantes de la semana hasta viernes
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timedelta, time
from dataclasses import dataclass
from typing import List, Optional

# Cargar environment variables desde .env manualmente (para cron/systemd)
env_file = Path.home() / '.hermes' / '.env'
if env_file.exists():
    for line in env_file.read_text().strip().split('\n'):
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ[key.strip()] = value.strip()

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class CalendarEvent:
    """Representa un evento del calendario."""
    summary: str
    start_time: datetime
    end_time: Optional[datetime]
    location: Optional[str]
    is_all_day: bool

class CalendarWeeklyService:
    """Servicio para envío semanal automático de calendario."""
    
    def __init__(self):
        # Target de Telegram (tu chat personal)
        self.telegram_target = os.getenv('CALENDAR_TELEGRAM_TARGET', '882558885')
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        
        if not self.telegram_token:
            logger.error("TELEGRAM_BOT_TOKEN no configurado")
            sys.exit(1)
            
        logger.info(f"Calendar Weekly Service iniciado - Target: {self.telegram_target}")
    
    def get_google_credentials(self):
        """Obtiene credenciales de Google desde environment variables."""
        try:
            # Primero intentar desde env vars
            client_id = os.getenv('GOOGLE_CLIENT_ID')
            client_secret = os.getenv('GOOGLE_CLIENT_SECRET') 
            refresh_token = os.getenv('GOOGLE_REFRESH_TOKEN')
            
            if not all([client_id, client_secret, refresh_token]):
                # Fallback a AWS directo
                import boto3
                
                aws_client = boto3.client('secretsmanager', region_name='eu-west-1')
                secret = aws_client.get_secret_value(SecretId='hermes/prod')
                secrets = json.loads(secret['SecretString'])
                google_config = secrets['integrations']['google']['primary']
                
                client_id = google_config['clientId']
                client_secret = google_config['clientSecret']
                refresh_token = google_config['refreshToken']
                
            return {
                'client_id': client_id,
                'client_secret': client_secret,
                'refresh_token': refresh_token
            }
            
        except Exception as e:
            logger.error(f"Error obteniendo credenciales Google: {e}")
            raise
    
    def get_calendar_service(self):
        """Construye servicio de Google Calendar."""
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            
            creds_data = self.get_google_credentials()
            
            creds = Credentials(
                token=None,
                refresh_token=creds_data['refresh_token'],
                token_uri='https://oauth2.googleapis.com/token',
                client_id=creds_data['client_id'],
                client_secret=creds_data['client_secret']
            )
            
            return build('calendar', 'v3', credentials=creds)
            
        except Exception as e:
            logger.error(f"Error creando servicio Calendar: {e}")
            raise
    
    def get_week_remaining_events(self) -> List[CalendarEvent]:
        """Obtiene eventos que quedan en la semana hasta el viernes."""
        service = self.get_calendar_service()
        
        now = datetime.now()
        
        # Calcular el próximo viernes a las 23:59
        days_until_friday = (4 - now.weekday()) % 7  # Viernes es weekday 4
        if days_until_friday == 0 and now.weekday() == 4:
            # Si es viernes, tomar el próximo viernes
            days_until_friday = 7
        
        friday_end = now.replace(hour=23, minute=59, second=59, microsecond=0) + timedelta(days=days_until_friday)
        
        # Buscar eventos desde ahora hasta el viernes (formato RFC3339 para Google API)
        time_min = now.isoformat() + 'Z' if now.tzinfo is None else now.isoformat()
        time_max = friday_end.isoformat() + 'Z' if friday_end.tzinfo is None else friday_end.isoformat()
        
        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min,
            timeMax=time_max,
            maxResults=50,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = []
        for event in events_result.get('items', []):
            start = event['start']
            end = event['end']
            
            # Determinar si es todo el día
            is_all_day = 'date' in start
            
            # Parsear fechas
            if is_all_day:
                start_time = datetime.fromisoformat(start['date'])
                end_time = datetime.fromisoformat(end['date']) if end.get('date') else None
            else:
                start_time = datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00'))
                end_time = datetime.fromisoformat(end['dateTime'].replace('Z', '+00:00')) if end.get('dateTime') else None
            
            events.append(CalendarEvent(
                summary=event.get('summary', 'Sin título'),
                start_time=start_time,
                end_time=end_time,
                location=event.get('location'),
                is_all_day=is_all_day
            ))
        
        return events
    
    def format_events_message(self, events: List[CalendarEvent]) -> str:
        """Formatea los eventos en mensaje de Telegram."""
        now = datetime.now()
        
        # Determinar período
        days_until_friday = (4 - now.weekday()) % 7
        if days_until_friday == 0 and now.weekday() == 4:
            days_until_friday = 7
        
        friday_date = now + timedelta(days=days_until_friday)
        
        # Crear mensaje
        header = f"""🗓️ **AGENDA SEMANAL**

📅 **Del {now.strftime('%d/%m')} al {friday_date.strftime('%d/%m/%Y')}**
⏰ **{len(events)} eventos programados**

"""
        
        if not events:
            return header + "🎉 ¡No tienes eventos pendientes esta semana!\n\n✨ Disfruta de tu tiempo libre"
        
        # Agrupar por día
        events_by_day = {}
        for event in events:
            day_key = event.start_time.date()
            if day_key not in events_by_day:
                events_by_day[day_key] = []
            events_by_day[day_key].append(event)
        
        body = ""
        for day, day_events in sorted(events_by_day.items()):
            # Nombre del día
            day_name = day.strftime('%A').replace(
                'Monday', 'lunes').replace('Tuesday', 'martes').replace(
                'Wednesday', 'miércoles').replace('Thursday', 'jueves').replace(
                'Friday', 'viernes').replace('Saturday', 'sábado').replace(
                'Sunday', 'domingo')
            
            # Determinar emoji del día
            if day == now.date():
                day_emoji = "📍"  # Hoy
            elif day < now.date():
                continue  # Saltar eventos pasados
            else:
                day_emoji = "📅"  # Futuro
            
            body += f"{day_emoji} **{day_name.capitalize()}, {day.strftime('%d/%m')}**\n"
            
            for event in day_events:
                if event.is_all_day:
                    time_str = "Todo el día"
                else:
                    time_str = event.start_time.strftime('%H:%M')
                    if event.end_time:
                        time_str += f" - {event.end_time.strftime('%H:%M')}"
                
                location_str = f" 📍 {event.location}" if event.location else ""
                body += f"   ⏰ {time_str} - {event.summary}{location_str}\n"
            
            body += "\n"
        
        footer = "🔄 Actualización automática diaria a las 20:00"
        
        return header + body + footer
    
    async def send_telegram_message(self, message: str) -> bool:
        """Envía mensaje a Telegram."""
        try:
            import aiohttp
            
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            
            payload = {
                'chat_id': self.telegram_target,
                'text': message,
                'parse_mode': 'Markdown',
                'disable_web_page_preview': True
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        logger.info("Mensaje enviado exitosamente a Telegram")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"Error enviando a Telegram: {response.status} - {error_text}")
                        return False
                        
        except Exception as e:
            logger.error(f"Error enviando mensaje: {e}")
            return False
    
    def should_run_today(self) -> bool:
        """Verifica si debe ejecutarse hoy (domingo a jueves)."""
        today = datetime.now().weekday()  # 0=Monday, 6=Sunday
        
        # Convertir a formato donde domingo=0
        if today == 6:  # Sunday
            today = 0
        else:
            today += 1
        
        # Ejecutar domingo(0) a jueves(4)
        return 0 <= today <= 4
    
    async def run_daily_update(self):
        """Ejecuta la actualización diaria."""
        if not self.should_run_today():
            logger.info("No se ejecuta hoy (solo domingo-jueves)")
            return
        
        try:
            logger.info("Iniciando actualización semanal de calendario...")
            
            # Obtener eventos
            events = self.get_week_remaining_events()
            logger.info(f"Obtenidos {len(events)} eventos")
            
            # Formatear mensaje
            message = self.format_events_message(events)
            
            # Enviar a Telegram
            success = await self.send_telegram_message(message)
            
            if success:
                logger.info("✅ Actualización semanal enviada exitosamente")
            else:
                logger.error("❌ Error enviando actualización semanal")
                
        except Exception as e:
            logger.error(f"Error en actualización diaria: {e}")
            raise

async def main():
    """Función principal."""
    try:
        service = CalendarWeeklyService()
        await service.run_daily_update()
        
    except Exception as e:
        logger.error(f"Error fatal en Calendar Weekly Service: {e}")
        sys.exit(1)

if __name__ == '__main__':
    asyncio.run(main())