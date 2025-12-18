"""
Heroku AppLink PDF Quote Generator Service
==========================================
A microservice that generates PDF quotes from Salesforce Opportunity data
and uploads them back to Salesforce via Heroku AppLink.
"""

import base64
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import heroku_applink as sdk
from weasyprint import HTML
# Global exception handler to ensure ALL errors return JSON
from starlette.exceptions import HTTPException as StarletteHTTPException

# =============================================================================
# Pydantic Models
# =============================================================================

class GenerateQuotePdfRequest(BaseModel):
    """Request model for PDF generation"""
    opportunityId: str = Field(
        ..., 
        description="The Salesforce Opportunity ID (18-character ID)",
        example="006XXXXXXXXXXXXXXX"
    )


class GenerateQuotePdfResponse(BaseModel):
    """Response model for successful PDF generation"""
    status: str = "success"
    message: str
    contentDocumentId: Optional[str] = None
    contentVersionId: Optional[str] = None


class ErrorResponse(BaseModel):
    """Error response model"""
    status: str = "error"
    message: str
    errorCode: str


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    version: str
    timestamp: str


# =============================================================================
# FastAPI App Configuration
# =============================================================================

app = FastAPI(
    title="Opportunity Quote PDF Generator API",
    description="A Heroku AppLink microservice that generates PDF quotes from Salesforce Opportunity data.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add Heroku AppLink middleware for secure Salesforce integration
app.add_middleware(sdk.IntegrationAsgiMiddleware)



@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle HTTP exceptions and return JSON"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "message": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
            "errorCode": "HTTP_ERROR"
        }
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch ALL exceptions (including middleware errors) and return JSON"""
    import traceback
        # Log the error (will appear in Heroku logs)
    print(f"Exception caught by global handler: {type(exc).__name__}: {str(exc)}")
    print(f"Traceback: {traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": f"Internal Server Error: {str(exc)}",
            "errorCode": "INTERNAL_ERROR",
            "exception_type": str(type(exc).__name__)
        }
    )


# =============================================================================
# PDF Generation Logic
# =============================================================================

def create_pdf_from_opportunity_data(opportunity_data: dict, quote_lines: list) -> bytes:
    """
    Generates a PDF byte string from Opportunity and Quote Line data.
    
    Args:
        opportunity_data: Dictionary containing Opportunity fields
        quote_lines: List of Quote Line Item records
    
    Returns:
        PDF as bytes
    """
    
    # Extract Opportunity data
    opp_name = opportunity_data.get('Name', 'N/A')
    opp_id = opportunity_data.get('Id', 'N/A')
    account_name = opportunity_data.get('Account', {}).get('Name', 'N/A') if isinstance(opportunity_data.get('Account'), dict) else 'N/A'
    amount = opportunity_data.get('Amount', 0) or 0
    close_date = opportunity_data.get('CloseDate', 'N/A')
    stage = opportunity_data.get('StageName', 'N/A')
    
    # Build quote line items table rows
    line_items_html = ""
    total_amount = 0
    
    for line in quote_lines:
        description = line.get('Description', 'N/A')
        quantity = line.get('Quantity', 0) or 0
        unit_price = line.get('UnitPrice', 0) or 0
        total_price = line.get('TotalPrice', 0) or 0
        total_amount += total_price
        
        line_items_html += f"""
            <tr>
                <td>{description}</td>
                <td style="text-align: center;">{quantity}</td>
                <td style="text-align: right;">${unit_price:,.2f}</td>
                <td style="text-align: right;">${total_price:,.2f}</td>
            </tr>
        """
    
    # Add total row
    line_items_html += f"""
        <tr class="total-row">
            <td colspan="3" style="text-align: right;"><strong>Total:</strong></td>
            <td style="text-align: right;"><strong>${total_amount:,.2f}</strong></td>
        </tr>
    """
    
    current_date = datetime.now().strftime("%B %d, %Y")
    
    # Build HTML content
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Quote for {opp_name}</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 40px; color: #333; }}
            .header {{ margin-bottom: 30px; }}
            .header h1 {{ color: #1798c1; margin-bottom: 10px; }}
            .meta-info {{ margin-bottom: 20px; }}
            .meta-info p {{ margin: 5px 0; }}
            table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
            th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
            th {{ background-color: #1798c1; color: white; font-weight: 600; }}
            tbody tr:nth-child(even) {{ background-color: #f9f9f9; }}
            .total-row {{ font-weight: bold; background-color: #e9ecef !important; }}
            .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; }}
            @page {{ size: A4; margin: 2cm; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Quote for {opp_name}</h1>
            <p><strong>Quote Date:</strong> {current_date}</p>
        </div>
        
        <div class="meta-info">
            <p><strong>Opportunity ID:</strong> {opp_id}</p>
            <p><strong>Account:</strong> {account_name}</p>
            <p><strong>Stage:</strong> {stage}</p>
            <p><strong>Expected Close Date:</strong> {close_date}</p>
            <p><strong>Opportunity Amount:</strong> ${amount:,.2f}</p>
        </div>
        
        <h2>Quote Line Items</h2>
        <table>
            <thead>
                <tr>
                    <th>Description</th>
                    <th style="text-align: center;">Quantity</th>
                    <th style="text-align: right;">Unit Price</th>
                    <th style="text-align: right;">Total</th>
                </tr>
            </thead>
            <tbody>
                {line_items_html if quote_lines else '<tr><td colspan="4" style="text-align: center; color: #666;">No line items found</td></tr>'}
            </tbody>
        </table>
        
        <div class="footer">
            <p>Generated on {current_date}</p>
        </div>
    </body>
    </html>
    """
    
    # Convert HTML to PDF
    pdf_bytes = HTML(string=html_content).write_pdf()
    return pdf_bytes


# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Health check endpoint to verify service status."""
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        timestamp=datetime.now(timezone.utc).isoformat()
    )


@app.post(
    "/generate-quote-pdf", 
    response_model=GenerateQuotePdfResponse,
    responses={
        404: {"model": ErrorResponse},
        500: {"model": ErrorResponse}
    },
    tags=["Quote Generation"]
)
async def generate_quote_pdf(request: GenerateQuotePdfRequest):
    """
    Generates a PDF quote for the specified Salesforce Opportunity.
    
    Process:
    1. Query Salesforce for Opportunity and Quote Line Item data
    2. Generate PDF from the data
    3. Upload PDF to Salesforce as ContentVersion
    4. Link the PDF to the Opportunity record
    """
    try:
        # Get the secure client context from Heroku AppLink middleware
        client_context = sdk.get_client_context()
        data_api = client_context.data_api
        
        opportunity_id = request.opportunityId
        
        # Query Salesforce for Opportunity data
        opp_query = f"""
            SELECT Id, Name, Amount, StageName, CloseDate, Account.Name
            FROM Opportunity 
            WHERE Id = '{opportunity_id}' 
            LIMIT 1
        """
        
        opp_result = await data_api.query(opp_query)
        
        if not opp_result.records:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": "Opportunity not found", "errorCode": "NOT_FOUND"}
            )
        
        opp_record = opp_result.records[0].fields
        
        # Query for Quote Line Items
        quote_lines_query = f"""
            SELECT Id, Description, Quantity, UnitPrice, TotalPrice
            FROM QuoteLineItem 
            WHERE Quote.OpportunityId = '{opportunity_id}'
        """
        
        quote_lines_result = await data_api.query(quote_lines_query)
        quote_lines = [record.fields for record in quote_lines_result.records] if quote_lines_result.records else []
        
        # Generate PDF
        pdf_bytes = create_pdf_from_opportunity_data(opp_record, quote_lines)
        
        # Upload PDF to Salesforce
        opp_name = opp_record.get('Name', 'Quote')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        file_data = {
            "Title": f"Quote - {opp_name}",
            "PathOnClient": f"Quote_{opportunity_id}_{timestamp}.pdf",
            "VersionData": base64.b64encode(pdf_bytes).decode('utf-8'),
            "OwnerId": client_context.user.id,
            "Description": f"Auto-generated quote PDF for Opportunity: {opp_name}"
        }
        
        # Create ContentVersion
        cv_response = await data_api.create("ContentVersion", file_data)
        content_version_id = cv_response.id
        
        # Get ContentDocumentId
        cd_query = f"SELECT ContentDocumentId FROM ContentVersion WHERE Id = '{content_version_id}'"
        cd_result = await data_api.query(cd_query)
        content_document_id = cd_result.records[0].fields['ContentDocumentId']
        
        # Link PDF to Opportunity
        cdl_data = {
            "ContentDocumentId": content_document_id,
            "LinkedEntityId": opportunity_id,
            "ShareType": "V",
            "Visibility": "AllUsers"
        }
        await data_api.create("ContentDocumentLink", cdl_data)
        
        return GenerateQuotePdfResponse(
            status="success",
            message="PDF generated and attached to Opportunity.",
            contentDocumentId=content_document_id,
            contentVersionId=content_version_id
        )
        
    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content=e.detail if isinstance(e.detail, dict) else {"status": "error", "message": str(e.detail), "errorCode": "HTTP_ERROR"}
        )
    except Exception as e:
        print(f"Error generating PDF: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Internal Server Error: {str(e)}", "errorCode": "INTERNAL_ERROR"}
        )


@app.get("/", tags=["System"])
async def root():
    """Root endpoint with API information"""
    return {
        "name": "Opportunity Quote PDF Generator API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }
