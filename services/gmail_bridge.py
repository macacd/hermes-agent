#!/usr/bin/env python3
"""
Gmail Bridge Service - Real-time email processing via Pub/Sub

Escucha notificaciones de Gmail via Google Pub/Sub, procesa emails entrantes,
genera síntesis con IA e inyecta en conversaciones activas del agente.

Arquitectura:
1. Gmail Watch API → Google Pub/Sub Topic
2. Este servicio → Pull de Pub/Sub Subscription  
3. Procesa emails → Genera síntesis con IA
4. Inyecta síntesis → Conversación activa del agente
"""

import asyncio
import json
import logging
import os
import base64
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

import google.auth
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.cloud import pubsub_v1
from google.auth import default, external_account
from googleapiclient.discovery import build

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('gmail_bridge')


class GmailBridge:
    """
    Bridge entre Gmail y el agente Hermes via Pub/Sub.
    """
    
    def __init__(self):
        self.project_id = os.getenv('GOOGLE_PROJECT_ID', 'nanocode-workspace-1774050095')
        self.subscription_path = os.getenv('GMAIL_SUBSCRIPTION', 
                                         'projects/nanocode-workspace-1774050095/subscriptions/gmail-notifications-sub')
        self.telegram_target = os.getenv('GMAIL_TELEGRAM_TARGET', '-1003796258079')
        self.telegram_thread_id = os.getenv('GMAIL_TELEGRAM_THREAD', '1')
        self.max_messages = int(os.getenv('GMAIL_MAX_MESSAGES', '10'))
        
        # Credenciales
        self._gmail_service = None
        self._pubsub_client = None
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
    
    def _get_pubsub_credentials(self):
        """Obtiene credenciales para Pub/Sub usando External Account."""
        try:
            # Intentar usar las credenciales por defecto del ambiente AWS
            credentials, project = default()
            return credentials
        except Exception as e:
            logger.warning(f"Could not get default credentials: {e}")
            
            # Fallback: intentar cargar External Account manualmente
            from google.auth.aws import Credentials as AwsCredentials
            
            credentials_info = {
                "type": "external_account",
                "audience": "//iam.googleapis.com/projects/956760784996/locations/global/workloadIdentityPools/nanocode-aws-pool/providers/nanocode-aws-provider",
                "subject_token_type": "urn:ietf:params:aws:token-type:aws4_request",
                "token_url": "https://sts.googleapis.com/v1/token",
                "credential_source": {
                    "environment_id": "aws1",
                    "region_url": "http://169.254.169.254/latest/meta-data/placement/availability-zone",
                    "url": "http://169.254.169.254/latest/meta-data/iam/security-credentials",
                    "regional_cred_verification_url": "https://sts.{region}.amazonaws.com?Action=GetCallerIdentity&Version=2011-06-15",
                    "imdsv2_session_token_url": "http://169.254.169.254/latest/api/token"
                },
                "service_account_impersonation_url": "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/nanocode-pubsub@nanocode-workspace-1774050095.iam.gserviceaccount.com:generateAccessToken"
            }
            
            return AwsCredentials.from_info(credentials_info)
    
    @property
    def gmail_service(self):
        """Lazy loading del servicio de Gmail."""
        if not self._gmail_service:
            creds = self._get_gmail_credentials()
            self._gmail_service = build('gmail', 'v1', credentials=creds)
        return self._gmail_service
    
    @property 
    def pubsub_client(self):
        """Lazy loading del cliente de Pub/Sub."""
        if not self._pubsub_client:
            credentials = self._get_pubsub_credentials()
            self._pubsub_client = pubsub_v1.SubscriberClient(credentials=credentials)
        return self._pubsub_client
    
    async def setup_gmail_watch(self) -> bool:
        """
        Configura Gmail Watch API para enviar notificaciones al Pub/Sub topic.
        Debe ejecutarse cada 24 horas máximo.
        """
        try:
            topic_name = f"projects/{self.project_id}/topics/gmail-notifications"
            
            # Configurar watch request
            request = {
                'userId': 'me',
                'body': {
                    'topicName': topic_name,
                    'labelIds': ['INBOX'],
                    'labelFilterAction': 'include'
                }
            }
            
            # Ejecutar watch
            result = self.gmail_service.users().watch(**request).execute()
            
            logger.info(f"Gmail watch configured successfully. History ID: {result.get('historyId')}")
            return True
            
        except Exception as e:
            logger.error(f"Error setting up Gmail watch: {e}")
            return False
    
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
                'body_preview': body[:500] if body else 'Sin contenido',
                'body_full': body,
                'labels': message.get('labelIds', []),
                'snippet': message.get('snippet', ''),
                'size_estimate': message.get('sizeEstimate', 0),
                'timestamp': datetime.now().isoformat()
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
        Genera una síntesis de los emails usando IA.
        TODO: Integrar con el modelo de IA de Hermes.
        """
        if not emails:
            return ""
        
        # Por ahora, síntesis simple - TODO: usar IA real
        synthesis_parts = []
        
        synthesis_parts.append(f"📧 {len(emails)} nuevo(s) email(s) recibido(s):")
        
        for email in emails[:3]:  # Máximo 3 emails en la síntesis
            sender = email['sender'].split('<')[0].strip().replace('"', '')
            subject = email['subject'][:50] + "..." if len(email['subject']) > 50 else email['subject']
            
            synthesis_parts.append(f"• De: {sender}")
            synthesis_parts.append(f"  Asunto: {subject}")
            synthesis_parts.append(f"  Vista previa: {email['snippet'][:100]}...")
            synthesis_parts.append("")
        
        if len(emails) > 3:
            synthesis_parts.append(f"... y {len(emails) - 3} email(s) más.")
        
        return "\n".join(synthesis_parts)
    
    async def inject_synthesis_to_agent(self, synthesis: str):
        """
        Inyecta la síntesis en la conversación activa del agente.
        TODO: Implementar inyección real en el contexto del agente.
        """
        logger.info(f"Email synthesis ready for injection:\n{synthesis}")
        
        # TODO: Enviar via Telegram por ahora
        # En el futuro, inyectar directamente en el contexto del agente
        await self._send_telegram_notification(synthesis)
    
    async def _send_telegram_notification(self, message: str):
        """Envía notificación por Telegram (temporal)."""
        # TODO: Integrar con el sistema de Telegram de Hermes
        logger.info(f"[TELEGRAM] {message}")
    
    def process_pubsub_message(self, message) -> bool:
        """
        Procesa un mensaje de Pub/Sub de Gmail.
        """
        try:
            # Decodificar datos del mensaje
            data = json.loads(message.data.decode('utf-8'))
            history_id = data.get('historyId')
            email_address = data.get('emailAddress', 'me')
            
            logger.info(f"Processing Pub/Sub message - History ID: {history_id}, Email: {email_address}")
            
            # Obtener cambios desde el último history ID conocido
            # TODO: Implementar tracking del último history ID
            changes = self.gmail_service.users().history().list(
                userId='me',
                startHistoryId=history_id,
                historyTypes=['messageAdded'],
                maxResults=self.max_messages
            ).execute()
            
            new_emails = []
            
            if 'history' in changes:
                for history_item in changes['history']:
                    if 'messagesAdded' in history_item:
                        for message_added in history_item['messagesAdded']:
                            message_id = message_added['message']['id']
                            
                            # Procesar solo emails del INBOX
                            if 'INBOX' in message_added['message'].get('labelIds', []):
                                email_info = self.process_email_message(message_id)
                                if email_info:
                                    new_emails.append(email_info)
            
            # Generar síntesis si hay nuevos emails
            if new_emails:
                synthesis = self.generate_email_synthesis(new_emails)
                asyncio.create_task(self.inject_synthesis_to_agent(synthesis))
            
            message.ack()  # Confirmar procesamiento
            return True
            
        except Exception as e:
            logger.error(f"Error processing Pub/Sub message: {e}")
            message.nack()  # Rechazar mensaje para reintento
            return False
    
    async def listen_pubsub(self):
        """
        Escucha mensajes de Pub/Sub en un loop infinito.
        """
        logger.info(f"Starting Pub/Sub listener on {self.subscription_path}")
        
        def callback(message):
            """Callback para mensajes de Pub/Sub."""
            self.process_pubsub_message(message)
        
        # Flow control settings
        flow_control = pubsub_v1.types.FlowControl(max_messages=100)
        
        try:
            self._running = True
            
            # Configurar Gmail Watch al inicio
            await self.setup_gmail_watch()
            
            while self._running:
                try:
                    # Pull messages
                    streaming_pull_future = self.pubsub_client.subscribe(
                        self.subscription_path, 
                        callback=callback,
                        flow_control=flow_control
                    )
                    
                    logger.info("Listening for messages on Pub/Sub subscription...")
                    
                    # Mantener la conexión abierta
                    with self.pubsub_client:
                        try:
                            streaming_pull_future.result(timeout=300)  # 5 min timeout
                        except KeyboardInterrupt:
                            streaming_pull_future.cancel()
                            break
                        except Exception as e:
                            logger.error(f"Error in streaming pull: {e}")
                            await asyncio.sleep(30)  # Esperar antes de reintentar
                
                except Exception as e:
                    logger.error(f"Error in Pub/Sub listener: {e}")
                    await asyncio.sleep(60)  # Esperar antes de reintentar
                    
        except KeyboardInterrupt:
            logger.info("Shutting down Gmail Bridge...")
        finally:
            self._running = False
    
    async def start(self):
        """Inicia el servicio Gmail Bridge."""
        logger.info("Starting Gmail Bridge Service")
        await self.listen_pubsub()
    
    def stop(self):
        """Detiene el servicio Gmail Bridge."""
        logger.info("Stopping Gmail Bridge Service")
        self._running = False


async def main():
    """Función principal para ejecutar el Gmail Bridge."""
    bridge = GmailBridge()
    try:
        await bridge.start()
    except KeyboardInterrupt:
        bridge.stop()


if __name__ == "__main__":
    asyncio.run(main())