public class GenerateQuotePDFController {
    @AuraEnabled
    public static void processRecord(Id recordId){
        system.debug('Processed Record===>>>' + recordId);
        herokuapplink.HerokuApps herokuService = new herokuapplink.HerokuApps();
        herokuapplink.HerokuApps.generateQuotePdf_Request apiReq = new herokuapplink.HerokuApps.generateQuotePdf_Request();
        
        apiReq.body = new herokuapplink.HerokuApps_GenerateQuotePdfRequest();
        apiReq.body.opportunityId  = recordId;
        herokuapplink.HerokuApps.generateQuotePdf_Response apiRes = herokuService.generateQuotePdf(apiReq);
        system.debug('API Response===>>>' + apiRes);

    }
}