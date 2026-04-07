#!/usr/bin/env python3
"""
Gmail Bridge Simple - Polling version para inyección de emails en tiempo real

Versión simplificada que no depende de Pub/Sub, hace polling directo de Gmail
para detectar emails nuevos y generar síntesis para el agente.
"""

import asyncio
import json
import logging
import os
import base64
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('gmail_bridge_simple')


class GmailBridgeSimple:
    """
    Bridge simplificado entre Gmail y el agente Hermes.
    Usa polling en lugar de Pub/Sub para simplicidad.
    """
    
    def __init__(self):
        # Always use main user chat for Gmail notifications (same as Hermes Gateway)
        self.telegram_target = os.getenv('GMAIL_TELEGRAM_TARGET', '882558885')
        self.telegram_thread_id = os.getenv('GMAIL_TELEGRAM_THREAD', '1')
        self.max_messages = int(os.getenv('GMAIL_MAX_MESSAGES', '10'))
        self.poll_interval = 30  # Segundos entre checks
        
        # Estado para tracking
        self.last_check_time = None
        self.last_history_id = None
        self._gmail_service = None
        self._running = False
        
    def _get_gmail_credentials(self) -> Credentials:
        """Obtiene credenciales OAuth2 para Gmail API."""
        creds = Credentials(
            token=None,
            refresh_token=os.getenv('GMAIL_REFRESH_TOKEN'),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv('GMAIL_CLIENT_ID'),
            client_secret=os.getenv('GMAIL_CLIENT_SECRET')
            # No especificar scopes - usar los del refresh token existente
        )
        
        if not creds.valid:
            creds.refresh(Request())
        
        return creds
    
    @property
    def gmail_service(self):
        """Lazy loading del servicio de Gmail."""
        if not self._gmail_service:
            creds = self._get_gmail_credentials()
            self._gmail_service = build('gmail', 'v1', credentials=creds)
        return self._gmail_service
    
    def get_new_messages_since(self, since_time: datetime) -> List[str]:
        """
        Obtiene IDs de mensajes nuevos desde una fecha específica.
        """
        try:
            # Query para buscar mensajes recientes
            query = f"in:inbox after:{int(since_time.timestamp())}"
            
            result = self.gmail_service.users().messages().list(
                userId='me',
                q=query,
                maxResults=self.max_messages
            ).execute()
            
            messages = result.get('messages', [])
            message_ids = [msg['id'] for msg in messages]
            
            logger.info(f"Found {len(message_ids)} new messages since {since_time}")
            return message_ids
            
        except Exception as e:
            logger.error(f"Error getting new messages: {e}")
            return []
    
    def process_email_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        """
        Procesa un mensaje de email específico y extrae información relevante.
        """
        try:
            # Obtener el mensaje completo
            message = self.gmail_service.users().messages().get(
                userId='me', 
                id=message_id,
                format='full'
            ).execute()
            
            # Extraer headers importantes
            headers = message['payload'].get('headers', [])
            header_dict = {h['name'].lower(): h['value'] for h in headers}
            
            # Extraer cuerpo del email
            body = self._extract_email_body(message['payload'])
            
            # Información del email
            email_info = {
                'message_id': message_id,
                'thread_id': message.get('threadId'),
                'subject': header_dict.get('subject', 'Sin asunto'),
                'sender': header_dict.get('from', 'Desconocido'),
                'to': header_dict.get('to', ''),
                'date': header_dict.get('date', ''),
                'body_preview': body[:300] if body else 'Sin contenido',
                'body_full': body,
                'labels': message.get('labelIds', []),
                'snippet': message.get('snippet', ''),
                'size_estimate': message.get('sizeEstimate', 0),
                'timestamp': datetime.now().isoformat(),
                'internal_date': message.get('internalDate', '0')
            }
            
            return email_info
            
        except Exception as e:
            logger.error(f"Error processing email message {message_id}: {e}")
            return None
    
    def _extract_email_body(self, payload: Dict) -> str:
        """Extrae el cuerpo del email desde el payload de Gmail API."""
        body = ""
        
        if 'parts' in payload:
            # Email multiparte
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain':
                    data = part['body'].get('data', '')
                    if data:
                        body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                        break
        else:
            # Email simple
            if payload['mimeType'] == 'text/plain':
                data = payload['body'].get('data', '')
                if data:
                    body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
        
        return body.strip()
    
    def generate_email_synthesis(self, emails: List[Dict[str, Any]]) -> str:
        """
        Genera una síntesis de los emails.
        En el futuro: integrar con LLM para análisis más sofisticado.
        """
        if not emails:
            return ""
        
        synthesis_parts = []
        
        synthesis_parts.append(f"📧 {len(emails)} nuevo(s) email(s) en tiempo real:")
        synthesis_parts.append("")
        
        for i, email in enumerate(emails[:3], 1):  # Máximo 3 emails
            sender = email['sender'].split('<')[0].strip().replace('"', '')
            if len(sender) > 30:
                sender = sender[:30] + "..."
                
            subject = email['subject']
            if len(subject) > 60:
                subject = subject[:60] + "..."
            
            # Extraer contenido clave del snippet
            snippet = email['snippet'][:150] + "..." if len(email['snippet']) > 150 else email['snippet']
            
            synthesis_parts.append(f"{i}. 👤 {sender}")
            synthesis_parts.append(f"   📋 {subject}")
            synthesis_parts.append(f"   💭 {snippet}")
            
            # Si hay palabras clave importantes, destacarlas
            important_keywords = ['urgent', 'importante', 'factura', 'invoice', 'payment', 'error', 'problema']
            content_lower = (subject + " " + snippet).lower()
            found_keywords = [kw for kw in important_keywords if kw in content_lower]
            
            if found_keywords:
                synthesis_parts.append(f"   🚨 Palabras clave: {', '.join(found_keywords)}")
            
            synthesis_parts.append("")
        
        if len(emails) > 3:
            synthesis_parts.append(f"... y {len(emails) - 3} email(s) más.")
            synthesis_parts.append("")
        
        synthesis_parts.append(f"⏰ {datetime.now().strftime('%H:%M:%S')}")
        
        return "\n".join(synthesis_parts)
    
    async def inject_synthesis_to_agent(self, synthesis: str):
        """
        Inyecta la síntesis en la conversación del agente.
        Por ahora solo loggea - en el futuro integrar con hermes.
        """
        logger.info("📨 NEW EMAIL SYNTHESIS FOR AGENT:")
        logger.info("="*80)
        for line in synthesis.split('\n'):
            logger.info(line)
        logger.info("="*80)
        
        # TODO: Implementar inyección real en el contexto del agente
        # Posibles approaches:
        # 1. Enviar a canal de Telegram del agente
        # 2. Escribir a un archivo que el agente monitoree
        # 3. Llamar a una API de hermes directamente
        # 4. Usar un sistema de colas (Redis, etc.)
        
        # Por ahora, simular notificación
        await self._simulate_agent_notification(synthesis)
    
    async def _simulate_agent_notification(self, message: str):
        """Simula la notificación al agente."""
        # Escribir a archivo temporal que el agente podría monitorear
        notifications_dir = Path.home() / ".hermes" / "notifications"
        notifications_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        notification_file = notifications_dir / f"email_synthesis_{timestamp}.txt"
        
        notification_content = f"""
NUEVA SÍNTESIS DE EMAILS
========================
Timestamp: {datetime.now().isoformat()}
Source: Gmail Bridge Simple

{message}

========================
End of synthesis
"""
        
        notification_file.write_text(notification_content)
        logger.info(f"📁 Notification saved to: {notification_file}")
    
    async def poll_for_new_emails(self):
        """
        Polling loop principal para detectar emails nuevos.
        """
        logger.info("Starting email polling...")
        
        # Inicializar tiempo de último check
        if self.last_check_time is None:
            # Empezar desde hace 1 hora para no procesar emails muy antiguos
            self.last_check_time = datetime.now() - timedelta(hours=1)
        
        while self._running:
            try:
                logger.debug(f"Checking for emails since {self.last_check_time}")
                
                # Buscar emails nuevos
                new_message_ids = self.get_new_messages_since(self.last_check_time)
                
                if new_message_ids:
                    logger.info(f"📧 Processing {len(new_message_ids)} new emails")
                    
                    # Procesar emails nuevos
                    processed_emails = []
                    for msg_id in new_message_ids:
                        email_info = self.process_email_message(msg_id)
                        if email_info:
                            processed_emails.append(email_info)
                    
                    # Generar síntesis
                    if processed_emails:
                        synthesis = self.generate_email_synthesis(processed_emails)
                        await self.inject_synthesis_to_agent(synthesis)
                
                # Actualizar timestamp del último check
                self.last_check_time = datetime.now()
                
                # Esperar antes del próximo poll
                await asyncio.sleep(self.poll_interval)
                
            except Exception as e:
                logger.error(f"Error in polling loop: {e}")
                await asyncio.sleep(60)  # Esperar más tiempo en caso de error
    
    async def start(self):
        """Inicia el Gmail Bridge Simple."""
        logger.info("🚀 Starting Gmail Bridge Simple")
        
        # Test de conexión inicial
        try:
            profile = self.gmail_service.users().getProfile(userId='me').execute()
            logger.info(f"✅ Connected to Gmail: {profile.get('emailAddress')}")
            logger.info(f"📊 Total messages: {profile.get('messagesTotal', 0)}")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Gmail: {e}")
            return
        
        # Iniciar polling
        self._running = True
        await self.poll_for_new_emails()
    
    def stop(self):
        """Detiene el Gmail Bridge Simple."""
        logger.info("⏹️ Stopping Gmail Bridge Simple")
        self._running = False


async def main():
    """Función principal para ejecutar el Gmail Bridge Simple."""
    bridge = GmailBridgeSimple()
    try:
        await bridge.start()
    except KeyboardInterrupt:
        bridge.stop()
        logger.info("👋 Gmail Bridge Simple stopped")


if __name__ == "__main__":
    asyncio.run(main())