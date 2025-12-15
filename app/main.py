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
from pydantic import BaseModel, Field
from heroku_applink import IntegrationAsgiMiddleware, get_client_context
from heroku_applink.data_api import DataAPI
from weasyprint import HTML

# =============================================================================
# Pydantic Models (matching OpenAPI spec)
# =============================================================================

class GenerateQuotePdfRequest(BaseModel):
    """Request model for PDF generation"""
    opportunityId: str = Field(
        ..., 
        description="The Salesforce Opportunity ID (18-character ID)",
        pattern=r'^006[a-zA-Z0-9]{15}$',
        example="006XXXXXXXXXXXXXXX"
    )
    includeTerms: bool = Field(
        default=False, 
        description="Whether to include terms and conditions in the PDF"
    )
    templateName: str = Field(
        default="standard",
        description="Name of the PDF template to use"
    )
    customHeader: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Custom header text for the PDF"
    )
    customFooter: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Custom footer text for the PDF"
    )


class GenerateQuotePdfResponse(BaseModel):
    """Response model for successful PDF generation"""
    status: str = "success"
    message: str
    contentDocumentId: Optional[str] = None
    contentVersionId: Optional[str] = None
    pdfUrl: Optional[str] = None


class ErrorResponse(BaseModel):
    """Error response model"""
    status: str = "error"
    message: str
    errorCode: str
    details: Optional[dict] = None


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    version: str
    timestamp: str


class Template(BaseModel):
    """PDF Template model"""
    name: str
    description: str
    isDefault: bool = False


class TemplatesResponse(BaseModel):
    """Templates list response"""
    templates: list[Template]


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
app.add_middleware(IntegrationAsgiMiddleware)

# =============================================================================
# PDF Templates
# =============================================================================

AVAILABLE_TEMPLATES = [
    Template(name="standard", description="Standard quote template", isDefault=True),
    Template(name="professional", description="Professional quote with company branding", isDefault=False),
    Template(name="minimal", description="Minimal clean design", isDefault=False),
]

TERMS_AND_CONDITIONS = """
<div class="terms">
    <h3>Terms and Conditions</h3>
    <ol>
        <li>This quote is valid for 30 days from the date of issue.</li>
        <li>Payment terms: Net 30 days from invoice date.</li>
        <li>Prices are subject to change without prior notice.</li>
        <li>Delivery dates are estimated and subject to confirmation.</li>
        <li>All sales are final unless otherwise specified in writing.</li>
    </ol>
</div>
"""


# =============================================================================
# PDF Generation Logic
# =============================================================================

def get_template_styles(template_name: str) -> str:
    """Returns CSS styles based on template name"""
    
    base_styles = """
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 40px; color: #333; }
        .header { margin-bottom: 30px; }
        .header h1 { margin-bottom: 10px; }
        .meta-info { margin-bottom: 20px; }
        .meta-info p { margin: 5px 0; }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
        th { background-color: #f8f9fa; font-weight: 600; }
        tbody tr:nth-child(even) { background-color: #f9f9f9; }
        .total-row { font-weight: bold; background-color: #e9ecef !important; }
        .footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; }
        .terms { margin-top: 30px; padding: 20px; background-color: #f8f9fa; border-radius: 5px; }
        .terms h3 { margin-bottom: 15px; }
        .terms ol { margin-left: 20px; }
        .terms li { margin: 5px 0; }
    """
    
    template_specific = {
        "standard": """
            .header h1 { color: #1798c1; }
            th { background-color: #1798c1; color: white; }
        """,
        "professional": """
            .header { border-bottom: 3px solid #2c3e50; padding-bottom: 20px; }
            .header h1 { color: #2c3e50; }
            th { background-color: #2c3e50; color: white; }
            .footer { text-align: center; color: #666; }
        """,
        "minimal": """
            .header h1 { color: #333; font-weight: 300; }
            table { border: none; }
            th, td { border: none; border-bottom: 1px solid #eee; }
            th { background-color: transparent; color: #666; text-transform: uppercase; font-size: 12px; }
        """
    }
    
    return base_styles + template_specific.get(template_name, template_specific["standard"])


def create_pdf_from_opportunity_data(
    opportunity_data: dict, 
    quote_lines: list,
    include_terms: bool = False,
    template_name: str = "standard",
    custom_header: Optional[str] = None,
    custom_footer: Optional[str] = None
) -> bytes:
    """
    Generates a PDF byte string from Opportunity and Quote Line data.
    
    Args:
        opportunity_data: Dictionary containing Opportunity fields
        quote_lines: List of Quote Line Item records
        include_terms: Whether to include terms and conditions
        template_name: Name of the template to use
        custom_header: Custom header text
        custom_footer: Custom footer text
    
    Returns:
        PDF as bytes
    """
    
    opp_name = opportunity_data.get('Name', 'N/A')
    opp_id = opportunity_data.get('Id', 'N/A')
    account_name = opportunity_data.get('Account', {}).get('Name', 'N/A') if isinstance(opportunity_data.get('Account'), dict) else opportunity_data.get('Account.Name', 'N/A')
    amount = opportunity_data.get('Amount', 0) or 0
    close_date = opportunity_data.get('CloseDate', 'N/A')
    stage = opportunity_data.get('StageName', 'N/A')
    
    # Build quote line items table rows
    line_items_html = ""
    total_amount = 0
    
    for line in quote_lines:
        fields = line.get('fields', line) if isinstance(line, dict) else {}
        name = fields.get('Name', 'N/A')
        quantity = fields.get('Quantity', 0) or 0
        unit_price = fields.get('UnitPrice', 0) or 0
        total_price = fields.get('TotalPrice', 0) or 0
        total_amount += total_price
        
        line_items_html += f"""
            <tr>
                <td>{name}</td>
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
    
    # Build the complete HTML
    styles = get_template_styles(template_name)
    current_date = datetime.now().strftime("%B %d, %Y")
    
    header_section = f"<p class='custom-header'>{custom_header}</p>" if custom_header else ""
    footer_section = f"<p class='custom-footer'>{custom_footer}</p>" if custom_footer else ""
    terms_section = TERMS_AND_CONDITIONS if include_terms else ""
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Quote for {opp_name}</title>
        <style>
            {styles}
            @page {{
                size: A4;
                margin: 2cm;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            {header_section}
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
                    <th>Item Name</th>
                    <th style="text-align: center;">Quantity</th>
                    <th style="text-align: right;">Unit Price</th>
                    <th style="text-align: right;">Total</th>
                </tr>
            </thead>
            <tbody>
                {line_items_html if quote_lines else '<tr><td colspan="4" style="text-align: center; color: #666;">No line items found</td></tr>'}
            </tbody>
        </table>
        
        {terms_section}
        
        <div class="footer">
            {footer_section}
            <p>Generated on {current_date}</p>
        </div>
    </body>
    </html>
    """
    
    # Convert HTML to PDF using WeasyPrint
    pdf_bytes = HTML(string=html_content).write_pdf()
    return pdf_bytes


# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """
    Health check endpoint to verify service status.
    Returns the current health status, version, and timestamp.
    """
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        timestamp=datetime.now(timezone.utc).isoformat()
    )


@app.get("/templates", response_model=TemplatesResponse, tags=["Templates"])
async def list_templates():
    """
    Returns a list of available PDF templates for quote generation.
    """
    return TemplatesResponse(templates=AVAILABLE_TEMPLATES)


@app.post(
    "/generate-quote-pdf", 
    response_model=GenerateQuotePdfResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        500: {"model": ErrorResponse}
    },
    tags=["Quote Generation"]
)
async def generate_quote_pdf(request: GenerateQuotePdfRequest):
    """
    Generates a PDF quote document for the specified Salesforce Opportunity.
    
    The PDF is created from the Opportunity details and associated Quote Line Items,
    then uploaded back to Salesforce and linked to the Opportunity record.
    
    **Process:**
    1. Query Salesforce for Opportunity and Quote Line Item data
    2. Generate PDF using the specified template
    3. Upload PDF to Salesforce as ContentVersion
    4. Link the PDF to the Opportunity record via ContentDocumentLink
    
    **Returns:**
    - ContentDocumentId and ContentVersionId of the uploaded PDF
    """
    try:
        # Get the secure client context from Heroku AppLink middleware
        client_context = get_client_context()
        data_api: DataAPI = client_context.data_api
        
        opportunity_id = request.opportunityId
        
        # Query Salesforce for Opportunity data
        opp_query = f"""
            SELECT 
                Id, 
                Name, 
                Amount, 
                StageName,
                CloseDate,
                Account.Id,
                Account.Name
            FROM Opportunity 
            WHERE Id = '{opportunity_id}' 
            LIMIT 1
        """
        
        opp_result = await data_api.query(opp_query)
        
        if not opp_result.records:
            raise HTTPException(
                status_code=404, 
                detail=ErrorResponse(
                    status="error",
                    message="Opportunity not found",
                    errorCode="NOT_FOUND"
                ).model_dump()
            )
        
        opp_record = opp_result.records[0].fields
        
        # Query for Quote Line Items associated with this Opportunity
        quote_lines_query = f"""
            SELECT 
                Id, 
                Name, 
                Quantity, 
                UnitPrice, 
                TotalPrice,
                Quote.Name
            FROM QuoteLineItem 
            WHERE Quote.OpportunityId = '{opportunity_id}'
        """
        
        quote_lines_result = await data_api.query(quote_lines_query)
        quote_lines = [record.fields for record in quote_lines_result.records] if quote_lines_result.records else []
        
        # Generate PDF
        pdf_bytes = create_pdf_from_opportunity_data(
            opportunity_data=opp_record,
            quote_lines=quote_lines,
            include_terms=request.includeTerms,
            template_name=request.templateName,
            custom_header=request.customHeader,
            custom_footer=request.customFooter
        )
        
        # Upload PDF to Salesforce as ContentVersion
        opp_name = opp_record.get('Name', 'Quote')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        file_data = {
            "Title": f"Quote - {opp_name}",
            "PathOnClient": f"Quote_{opportunity_id}_{timestamp}.pdf",
            "VersionData": base64.b64encode(pdf_bytes).decode('utf-8'),
            "OwnerId": client_context.user.id,
            "Description": f"Auto-generated quote PDF for Opportunity: {opp_name}"
        }
        
        # Create ContentVersion (the file)
        cv_response = await data_api.create("ContentVersion", file_data)
        content_version_id = cv_response.id
        
        # Query to get the ContentDocumentId
        cd_query = f"SELECT ContentDocumentId FROM ContentVersion WHERE Id = '{content_version_id}'"
        cd_result = await data_api.query(cd_query)
        content_document_id = cd_result.records[0].fields['ContentDocumentId']
        
        # Create ContentDocumentLink to link the file to the Opportunity
        cdl_data = {
            "ContentDocumentId": content_document_id,
            "LinkedEntityId": opportunity_id,
            "ShareType": "V",  # Viewer permission
            "Visibility": "AllUsers"
        }
        await data_api.create("ContentDocumentLink", cdl_data)
        
        # Build response
        instance_url = getattr(client_context, 'instance_url', '')
        pdf_url = f"{instance_url}/{content_document_id}" if instance_url else None
        
        return GenerateQuotePdfResponse(
            status="success",
            message="PDF generated and attached to Opportunity.",
            contentDocumentId=content_document_id,
            contentVersionId=content_version_id,
            pdfUrl=pdf_url
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error generating PDF: {e}")
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                status="error",
                message=f"Internal Server Error: {str(e)}",
                errorCode="INTERNAL_ERROR",
                details={"exception": str(type(e).__name__)}
            ).model_dump()
        )


# =============================================================================
# Root endpoint
# =============================================================================

@app.get("/", tags=["System"])
async def root():
    """Root endpoint with API information"""
    return {
        "name": "Opportunity Quote PDF Generator API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }

